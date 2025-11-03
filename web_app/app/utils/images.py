# app/utils/images.py
# handlers for image manipulation

import os
import re
import mimetypes
from datetime import datetime
from PIL import Image, TiffImagePlugin, ImageOps
from PIL.ExifTags import IFD, GPSTAGS, TAGS

# No DoS by extreme big pics
Image.MAX_IMAGE_PIXELS = 80_000_000  # ~80 MPx

# --- MIME detection ---
try:
    import magic  # python-magic
    _HAS_MAGIC = True
except Exception:
    _HAS_MAGIC = False

def detect_mime(file_path: str) -> str:
    if _HAS_MAGIC:
        # Magic objekt create only once
        m = magic.Magic(mime=True)
        return m.from_file(file_path)
    mt, _ = mimetypes.guess_type(file_path)
    return mt or "application/octet-stream"


# --- Thumbnails ---
_RASTER_EXTS = {"jpg", "jpeg", "png", "tif", "tiff"}

def make_thumbnail(src_path: str, dst_thumb_path: str, max_side: int) -> bool:
    ext = os.path.splitext(src_path)[1].lstrip(".").lower()
    if ext not in _RASTER_EXTS:
        return False
    with Image.open(src_path) as im:
        # Keep EXIF orientation (mostly for mobiles)
        try:
            im = ImageOps.exif_transpose(im)
        except Exception:
            pass
        if im.mode not in ("RGB", "RGBA"):
            im = im.convert("RGB")
        im.thumbnail((max_side, max_side))
        os.makedirs(os.path.dirname(dst_thumb_path), exist_ok=True)
        im.save(dst_thumb_path, format="JPEG", quality=80, optimize=True)
    return True


# --- Sanitization of text/EXIF to JSON ---
# PostgreSQL jsonb will not tolerate \u0000 and other zeros.
_CTRL_RE = re.compile(r"[\x00-\x08\x0B\x0C\x0E-\x1F]")  # all except \t \n \r

def _clean_text(s: str) -> str:
    if not isinstance(s, str):
        s = str(s)
    return _CTRL_RE.sub("", s)

def _jsonable(o):
    if isinstance(o, (int, float, bool)) or o is None:
        return o
    if isinstance(o, str):
        return _clean_text(o)
    if isinstance(o, bytes):
        return _clean_text(o.decode("utf-8", "replace"))
    if isinstance(o, (list, tuple)):
        return [_jsonable(x) for x in o]
    if isinstance(o, dict):
        return {str(k): _jsonable(v) for k, v in o.items()}
    if isinstance(o, TiffImagePlugin.IFDRational):
        try:
            return float(o)
        except Exception:
            return _clean_text(str(o))
    return _clean_text(str(o))


# --- Human readable map + whitelist for "compact" EXIF ---
_EXIF_HUMAN = {
    # 0th/ImageIFD
    271: "Make", 272: "Model", 305: "Software", 306: "DateTime",
    256: "ImageWidth", 257: "ImageHeight",
    # ExifIFD
    33434: "ExposureTime", 33437: "FNumber", 34850: "ExposureProgram",
    34855: "ISO", 37377: "ShutterSpeedValue", 37378: "ApertureValue",
    37383: "MeteringMode", 37385: "Flash", 37386: "FocalLength",
    40962: "ExifImageWidth", 40963: "ExifImageHeight",
    41989: "FocalLengthIn35mmFilm",
    36867: "DateTimeOriginal", 36868: "CreateDate",
}

# Big noisy tags (typically DJI MakerNote) will be ignored
_EXIF_DROP_KEYS = {37500, 40092, 40094, 41728, 41729}

def _ratio_to_float(v):
    try:
        if isinstance(v, TiffImagePlugin.IFDRational):
            return float(v)
        if isinstance(v, (list, tuple)) and len(v) == 2 and v[1]:
            return v[0] / v[1]
        return float(v)
    except Exception:
        return None

def _dms_to_deg(dms, ref):
    try:
        d, m, s = dms
        d = _ratio_to_float(d); m = _ratio_to_float(m); s = _ratio_to_float(s)
        if None in (d, m, s):
            return None
        v = d + m/60.0 + s/3600.0
        if ref in ("S", "W"):
            v = -v
        return v
    except Exception:
        return None

def _parse_piexif_gps(gps_ifd):
    # piexif GPS keys: 1=LatRef,2=Lat,3=LonRef,4=Lon,5=AltRef,6=Alt
    lat_ref = gps_ifd.get(1); lon_ref = gps_ifd.get(3)
    lat_val = gps_ifd.get(2); lon_val = gps_ifd.get(4)
    alt_ref = gps_ifd.get(5); alt_val = gps_ifd.get(6)

    if isinstance(lat_ref, bytes): lat_ref = lat_ref.decode("utf-8", "ignore")
    if isinstance(lon_ref, bytes): lon_ref = lon_ref.decode("utf-8", "ignore")

    lat = _dms_to_deg(lat_val, lat_ref) if (lat_ref and lat_val) else None
    lon = _dms_to_deg(lon_val, lon_ref) if (lon_ref and lon_val) else None

    alt = None
    if alt_val is not None:
        a = _ratio_to_float(alt_val)
        if a is not None:
            try:
                ref = int(alt_ref) if alt_ref is not None else 0
            except Exception:
                ref = 0
            alt = -a if ref == 1 else a
    return lat, lon, alt

def _compact_exif_from_piexif(exif_dict: dict, gps_lat, gps_lon, gps_alt) -> dict:
    out = {}
    def put_human(section: dict):
        for k, v in section.items():
            if k in _EXIF_DROP_KEYS:
                continue
            name = _EXIF_HUMAN.get(k)
            if not name:
                continue
            if isinstance(v, bytes):
                v = v.decode("utf-8", "ignore")
            elif isinstance(v, (list, tuple)):
                if len(v) == 2 and all(isinstance(x, int) for x in v):
                    vv = _ratio_to_float(v)
                    v = vv if vv is not None else _clean_text(str(v))
                else:
                    v = [_jsonable(x) for x in v]
            else:
                v = _jsonable(v)
            out[name] = v

    put_human(exif_dict.get("0th", {}))
    put_human(exif_dict.get("Exif", {}))

    if gps_lat is not None: out["GPSLatitude"]  = gps_lat
    if gps_lon is not None: out["GPSLongitude"] = gps_lon
    if gps_alt is not None: out["GPSAltitude"]  = gps_alt
    return out

# cutting jsons only for several tags
def _shrink_json(obj: dict, max_bytes: int) -> dict:
    import json
    essential = [
        "Make","Model","Software","DateTimeOriginal","CreateDate","DateTime",
        "ExposureTime","FNumber","ISO","ShutterSpeedValue","ApertureValue",
        "FocalLength","FocalLengthIn35mmFilm","ExposureProgram","MeteringMode","Flash",
        "ImageWidth","ImageHeight","ExifImageWidth","ExifImageHeight",
        "GPSLatitude","GPSLongitude","GPSAltitude",
    ]
    slim = {k: obj[k] for k in essential if k in obj}
    if len(json.dumps(slim, ensure_ascii=False).encode("utf-8")) <= max_bytes:
        return slim
    # if json still big, cutting textes
    for k, v in list(slim.items()):
        if isinstance(v, str) and len(v) > 80:
            slim[k] = v[:80]
    return slim


# --- Core: EXIF extraktion (piexif but if not working then fallback Pillow) ---
def extract_exif(path: str):
    from config import Config  # for import cycling
    shoot_dt = gps_lat = gps_lon = gps_alt = None

    # 1) Primarily piexif (most reliable for GPS)
    try:
        import piexif
        exif_data = piexif.load(path)  # {"0th","Exif","GPS","1st",...}

        # datetime
        dto = exif_data.get("Exif", {}).get(piexif.ExifIFD.DateTimeOriginal) \
              or exif_data.get("0th", {}).get(piexif.ImageIFD.DateTime)
        if isinstance(dto, bytes):
            dto = dto.decode("utf-8", "ignore")
        if isinstance(dto, str):
            try:
                shoot_dt = datetime.fromisoformat(dto.replace(":", "-", 2))
            except Exception:
                pass

        # GPS
        gps_ifd = exif_data.get("GPS", {})
        if gps_ifd:
            gps_lat, gps_lon, gps_alt = _parse_piexif_gps(gps_ifd)

        # exif_json (compact vs full)
        if getattr(Config, "EXIF_STORE_MODE", "compact") == "compact":
            compact = _compact_exif_from_piexif(exif_data, gps_lat, gps_lon, gps_alt)
            compact = _jsonable(compact)
            from json import dumps
            if len(dumps(compact, ensure_ascii=False).encode("utf-8")) > getattr(Config, "EXIF_MAX_JSON_BYTES", 32768):
                compact = _shrink_json(compact, getattr(Config, "EXIF_MAX_JSON_BYTES", 32768))
            return shoot_dt, gps_lat, gps_lon, gps_alt, compact
        else:
            full = _jsonable({
                "0th": exif_data.get("0th", {}),
                "Exif": exif_data.get("Exif", {}),
                "GPS": exif_data.get("GPS", {}),
                "1st": exif_data.get("1st", {}),
            })
            return shoot_dt, gps_lat, gps_lon, gps_alt, full

    except Exception:
        # 2) Fallback: Pillow (getexif + GPS IFD)
        try:
            with Image.open(path) as im:
                raw = im.getexif()
                if not raw:
                    return None, None, None, None, {}

                # toplevel EXIF map (int tag -> human name)
                exif_top = {TAGS.get(k, k): v for k, v in raw.items()}

                # datetime
                dto = exif_top.get("DateTimeOriginal") or exif_top.get("DateTime")
                if isinstance(dto, str):
                    try:
                        shoot_dt = datetime.fromisoformat(dto.replace(":", "-", 2))
                    except Exception:
                        shoot_dt = None

                # GPS IFD
                gps_ifd = None
                if hasattr(raw, "get_ifd"):
                    try:
                        gps_ifd = raw.get_ifd(IFD.GPS)
                    except Exception:
                        gps_ifd = None
                if gps_ifd and hasattr(gps_ifd, "items"):
                    gps_named = {GPSTAGS.get(k, k): v for k, v in gps_ifd.items()}
                    lat_ref = gps_named.get("GPSLatitudeRef");  lat_val = gps_named.get("GPSLatitude")
                    lon_ref = gps_named.get("GPSLongitudeRef"); lon_val = gps_named.get("GPSLongitude")
                    alt_ref = gps_named.get("GPSAltitudeRef");  alt_val = gps_named.get("GPSAltitude")
                    if lat_ref and lat_val and lon_ref and lon_val:
                        gps_lat = _dms_to_deg(lat_val, lat_ref)
                        gps_lon = _dms_to_deg(lon_val, lon_ref)
                    if alt_val is not None:
                        a = _ratio_to_float(alt_val)
                        if a is not None:
                            try:
                                ref = int(alt_ref) if alt_ref is not None else 0
                            except Exception:
                                ref = 0
                            gps_alt = -a if ref == 1 else a
                    # for readibility could be added GPSIFD to JSON as well
                    exif_top["GPSIFD"] = {str(k): v for k, v in gps_named.items()}

                # JSON out (compact vs full)
                exif_clean = _jsonable(exif_top)
                if getattr(Config, "EXIF_STORE_MODE", "compact") == "compact":
                    compact = {
                        k: exif_clean.get(k) for k in (
                            "Make","Model","Software","DateTimeOriginal","CreateDate","DateTime",
                            "ExposureTime","FNumber","ISO","FocalLength",
                            "ImageWidth","ImageLength","ExifImageWidth","ExifImageHeight",
                        ) if exif_clean.get(k) is not None
                    }
                    if gps_lat is not None: compact["GPSLatitude"]  = gps_lat
                    if gps_lon is not None: compact["GPSLongitude"] = gps_lon
                    if gps_alt is not None: compact["GPSAltitude"]  = gps_alt
                    return shoot_dt, gps_lat, gps_lon, gps_alt, compact
                return shoot_dt, gps_lat, gps_lon, gps_alt, exif_clean

        except Exception:
            return None, None, None, None, {}
