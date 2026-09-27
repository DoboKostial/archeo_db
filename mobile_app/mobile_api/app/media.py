import hashlib
import logging
import os
import re
import tempfile
from datetime import date
from uuid import uuid4

from PIL import Image, ImageOps

from config import Config

logger = logging.getLogger("mobile_api.media")

Image.MAX_IMAGE_PIXELS = 80_000_000

PHOTO_TYP_CHOICES = {"vertical", "horizontal", "skew", "general", "detail"}
SKETCH_TYP_CHOICES = {"sketch", "photosketch", "general", "other"}
PHOTOGRAM_TYP_CHOICES = {"stereo", "resection", "synthetic", "other"}

_THUMBNAIL_MIME_TYPES = {"image/jpeg", "image/png", "image/tiff"}

PK_REGEX = re.compile(r"^[0-9]+_[A-Za-z0-9._-]+\.[a-z0-9]+$")

# Base table and PK column per media kind, shared by all entity route modules.
_MEDIA_TABLES = {
    "photos": ("tab_photos", "id_photo"),
    "sketches": ("tab_sketches", "id_sketch"),
    "drawings": ("tab_drawings", "id_drawing"),
    "photograms": ("tab_photograms", "id_photogram"),
}


def _default_data_dir() -> str:
    return os.path.abspath(
        os.path.join(os.path.dirname(__file__), "../../../web_app/data"),
    )


def _data_dir() -> str:
    return getattr(Config, "DATA_DIR", None) or _default_data_dir()


def _media_dir(kind: str) -> str:
    configured = getattr(Config, "MEDIA_DIRS", None) or {
        "photos": "photos",
        "sketches": "sketches",
        "drawings": "drawings",
        "photograms": "photograms",
    }
    return configured[kind]


def _safe_join(*parts: str) -> str:
    return os.path.abspath(os.path.normpath(os.path.join(*parts)))


def _is_path_under(base_dir: str, path: str) -> bool:
    try:
        return os.path.commonpath([base_dir, path]) == base_dir
    except ValueError:
        return False


def _sanitize_filename(name: str):
    base, ext = os.path.splitext(name or "")
    ext = ext.lower().lstrip(".")
    safe_base = re.sub(r"[^A-Za-z0-9._-]", "_", base).strip("_")
    if not safe_base or not ext:
        raise ValueError("Invalid filename.")
    return safe_base, ext


def _db_prefix_from_name(dbname: str) -> str:
    match = re.match(r"^(\d+)_", dbname)
    if not match:
        raise ValueError("Terrain database must start with numeric prefix.")
    return f"{match.group(1)}_"


def _make_media_pk(terrain_db: str, original_name: str) -> str:
    prefix = _db_prefix_from_name(terrain_db)
    base, ext = _sanitize_filename(original_name)
    candidate = f"{prefix}{base}.{ext}"
    if PK_REGEX.match(candidate):
        return candidate
    raise ValueError("Invalid generated media identifier.")


def _make_unique_media_pk(cur, terrain_db: str, kind: str, original_name: str) -> str:
    table, id_col = _MEDIA_TABLES[kind]
    pk = _make_media_pk(terrain_db, original_name)
    cur.execute(
        f"SELECT 1 FROM {table} WHERE {id_col} = %s LIMIT 1",
        (pk,),
    )
    if cur.fetchone() is None:
        return pk

    base, ext = _sanitize_filename(original_name)
    pref = _db_prefix_from_name(terrain_db)
    candidate = f"{pref}{base}_{int(date.today().strftime('%Y%m%d'))}.{ext}"
    if candidate != pk:
        cur.execute(
            f"SELECT 1 FROM {table} WHERE {id_col} = %s LIMIT 1",
            (candidate,),
        )
        if cur.fetchone() is None:
            return candidate

    candidate = f"{pref}{base}_{uuid4().hex[:8]}.{ext}"
    validate = PK_REGEX.match(candidate)
    if not validate:
        raise ValueError("Generated media identifier is invalid.")
    return candidate


def _detect_mime(path: str, original_name: str) -> str:
    with open(path, "rb") as handle:
        header = handle.read(512)

    lower_name = (original_name or "").lower()
    if header.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if header.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if header[:4] in (b"II*\x00", b"MM\x00*"):
        return "image/tiff"
    if header.startswith(b"%PDF"):
        return "application/pdf"
    if lower_name.endswith(".svg") or b"<svg" in header.lower():
        return "image/svg+xml"
    raise ValueError("Unsupported media type.")


def _sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _media_file_path(terrain_db: str, kind: str, media_id: str) -> str:
    base_dir = _safe_join(_data_dir(), terrain_db, _media_dir(kind))
    file_path = _safe_join(base_dir, media_id)
    if not _is_path_under(base_dir, file_path):
        raise ValueError("Invalid media path.")
    return file_path


def _media_thumbnail_path(file_path: str) -> str:
    media_dir = os.path.dirname(file_path)
    media_name = os.path.splitext(os.path.basename(file_path))[0]
    thumb_path = _safe_join(media_dir, "thumbs", f"{media_name}.jpg")
    if not _is_path_under(media_dir, thumb_path):
        raise ValueError("Invalid thumbnail path.")
    return thumb_path


def _make_thumbnail(src_path: str, dst_path: str, max_side: int) -> None:
    thumb_dir = os.path.dirname(dst_path)
    os.makedirs(thumb_dir, exist_ok=True)
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=thumb_dir,
            prefix=".thumb-",
            suffix=".jpg",
            delete=False,
        ) as handle:
            temp_path = handle.name

        with Image.open(src_path) as image:
            image = ImageOps.exif_transpose(image)
            image.thumbnail((max_side, max_side))

            if image.mode in ("RGBA", "LA") or (
                image.mode == "P" and "transparency" in image.info
            ):
                rgba = image.convert("RGBA")
                rgb = Image.new("RGB", rgba.size, "white")
                rgb.paste(rgba, mask=rgba.getchannel("A"))
                image = rgb
            elif image.mode != "RGB":
                image = image.convert("RGB")

            image.save(temp_path, format="JPEG", quality=80, optimize=True)

        os.replace(temp_path, dst_path)
        temp_path = None
    finally:
        if temp_path and os.path.exists(temp_path):
            os.remove(temp_path)


def _remove_stored_media(file_path: str | None) -> None:
    if not file_path:
        return
    for path in (file_path, _media_thumbnail_path(file_path)):
        try:
            if os.path.exists(path):
                os.remove(path)
        except OSError:
            logger.warning("Failed to remove media file %s", path, exc_info=True)


def _ensure_author_exists(cur, author_email: str):
    cur.execute("SELECT 1 FROM gloss_personalia WHERE mail = %s LIMIT 1", (author_email,))
    return cur.fetchone() is not None


def _insert_media_row(cur, kind: str, media_id: str, media_type: str | None, author_email: str, notes: str | None, mime_type: str, file_size: int, checksum_sha256: str):
    today = date.today().isoformat()
    if kind == "photos":
        cur.execute(
            """
            INSERT INTO tab_photos (
                id_photo, photo_typ, datum, author, notes,
                mime_type, file_size, checksum_sha256,
                shoot_datetime, gps_lat, gps_lon, gps_alt, exif_json
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NULL, NULL, NULL, NULL, '{}'::jsonb)
            """,
            (media_id, media_type, today, author_email, notes, mime_type, file_size, checksum_sha256),
        )
    elif kind == "sketches":
        cur.execute(
            """
            INSERT INTO tab_sketches (
                id_sketch, sketch_typ, author, datum, notes,
                mime_type, file_size, checksum_sha256
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (media_id, media_type, author_email, today, notes, mime_type, file_size, checksum_sha256),
        )
    elif kind == "drawings":
        cur.execute(
            """
            INSERT INTO tab_drawings (
                id_drawing, author, datum, notes,
                mime_type, file_size, checksum_sha256
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (media_id, author_email, today, notes, mime_type, file_size, checksum_sha256),
        )
    else:
        cur.execute(
            """
            INSERT INTO tab_photograms (
                id_photogram, photogram_typ, datum, ref_sketch, notes,
                mime_type, file_size, checksum_sha256,
                ref_photo_from, ref_photo_to
            )
            VALUES (%s, %s, %s, NULL, %s, %s, %s, %s, NULL, NULL)
            """,
            (media_id, media_type, today, notes, mime_type, file_size, checksum_sha256),
        )


def _store_media_file(terrain_db: str, kind: str, media_id: str, file_storage):
    """Store an upload and its thumbnail on the shared data filesystem."""
    final_path = _media_file_path(terrain_db, kind, media_id)
    target_dir = os.path.dirname(final_path)
    temp_path = None
    try:
        os.makedirs(target_dir, exist_ok=True)

        # The temporary file must be on the target filesystem so os.replace
        # remains atomic when DATA_DIR is a separate mount.
        with tempfile.NamedTemporaryFile(
            dir=target_dir,
            prefix=".upload-",
            delete=False,
        ) as handle:
            temp_path = handle.name
            file_storage.save(handle)

        mime_type = _detect_mime(temp_path, file_storage.filename)
        file_size = os.path.getsize(temp_path)
        checksum_sha256 = _sha256_file(temp_path)

        os.replace(temp_path, final_path)
        temp_path = None

        if mime_type in _THUMBNAIL_MIME_TYPES:
            thumb_path = _media_thumbnail_path(final_path)
            try:
                _make_thumbnail(
                    final_path,
                    thumb_path,
                    int(getattr(Config, "THUMB_MAX_SIDE", 256)),
                )
            except Exception:
                logger.warning(
                    "Thumbnail creation failed for %s",
                    final_path,
                    exc_info=True,
                )

        return mime_type, file_size, checksum_sha256, final_path
    except Exception:
        if temp_path and os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                pass
        _remove_stored_media(final_path)
        raise


def _store_media_upload(cur, terrain_db: str, kind: str, file_storage, media_type, author_email: str, notes):
    """Save an uploaded file into the shared media directory and insert its
    media row. Returns (media_id, mime_type, final_path). On failure the
    stored files are removed before the exception propagates; the caller must
    call _remove_stored_media if the transaction fails after this returns."""
    final_path = None
    try:
        media_id = _make_unique_media_pk(cur, terrain_db, kind, file_storage.filename)
        mime_type, file_size, checksum_sha256, final_path = _store_media_file(
            terrain_db,
            kind,
            media_id,
            file_storage,
        )

        _insert_media_row(
            cur,
            kind,
            media_id,
            media_type,
            author_email,
            notes,
            mime_type,
            file_size,
            checksum_sha256,
        )
        return media_id, mime_type, final_path
    except Exception:
        _remove_stored_media(final_path)
        raise
