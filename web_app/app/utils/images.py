# app/utils/images.py
# handlers for image manipulation

import os
import mimetypes
from PIL import Image, ExifTags
from datetime import datetime


# --- MIME detection ---
try:
    import magic  # python-magic
    _HAS_MAGIC = True
except Exception:
    _HAS_MAGIC = False

def detect_mime(file_path: str) -> str:
    if _HAS_MAGIC:
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
        if im.mode not in ("RGB", "RGBA"):
            im = im.convert("RGB")
        im.thumbnail((max_side, max_side))
        os.makedirs(os.path.dirname(dst_thumb_path), exist_ok=True)
        im.save(dst_thumb_path, format="JPEG", quality=85, optimize=True)
    return True


# --- EXIF extract (photos only) ---
def _ratio_to_float(r):
    return r[0] / r[1] if isinstance(r, tuple) and r[1] else float(r)


def _dms_to_deg(dms, ref):
    d, m, s = (_ratio_to_float(x) for x in dms)
    val = d + m/60 + s/3600
    if ref in ("S", "W"):
        val = -val
    return val

#   Returns: (shoot_datetime, gps_lat, gps_lon, gps_alt, exif_json)
#   Best-effort: on failure returns None/{}.
def extract_exif(path: str):
    try:
        with Image.open(path) as im:
            raw = im.getexif()
            if not raw:
                return None, None, None, None, {}
            exif = {ExifTags.TAGS.get(k, k): v for k, v in raw.items()}

            sdt = None
            dto = exif.get("DateTimeOriginal") or exif.get("DateTime")
            if isinstance(dto, str):
                dto = dto.replace(":", "-", 2)  # "YYYY:MM:DD HH:MM:SS" -> ISO-ish
                try:
                    sdt = datetime.fromisoformat(dto)
                except Exception:
                    sdt = None

            lat = lon = alt = None
            gps = exif.get("GPSInfo")
            if isinstance(gps, dict):
                try:
                    lat = _dms_to_deg(gps[2], gps[1])
                    lon = _dms_to_deg(gps[4], gps[3])
                    if 6 in gps:
                        ar = gps[6]
                        alt = _ratio_to_float(ar) if isinstance(ar, tuple) else float(ar)
                except Exception:
                    lat = lon = alt = None

            return sdt, lat, lon, alt, exif
    except Exception:
        return None, None, None, None, {}
