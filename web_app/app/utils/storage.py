# app/utils/storage.py
# handlers for storage and paths manipulation

import os, re, shutil, tempfile
from typing import Tuple
from werkzeug.datastructures import FileStorage

from config import Config

# --- PK building & validation ---
_DB_NAME_REGEX = re.compile(r"^[0-9][A-Za-z0-9_]*$")
_PK_REGEX = re.compile(r"^[0-9]+_[A-Za-z0-9._-]+\.[a-z0-9]+$")


def validate_db_name(dbname: str) -> None:
    if not isinstance(dbname, str) or not _DB_NAME_REGEX.fullmatch(dbname):
        raise ValueError("Invalid terrain database name.")

def db_prefix_from_name(dbname: str) -> str:
    m = re.match(r"^(\d+)_", dbname)
    if not m:
        raise ValueError("DB name must start with numeric prefix + underscore (e.g. '456_Project').")
    return f"{m.group(1)}_"

def _sanitize_filename(name: str) -> Tuple[str, str]:
    base, ext = os.path.splitext(name)
    ext = ext.lower().lstrip(".")
    safe_base = re.sub(r"[^A-Za-z0-9._-]", "_", base).strip("_")
    if not safe_base or not ext:
        raise ValueError("Invalid filename after sanitization.")
    return safe_base, ext

def make_pk(dbname: str, original_name: str) -> str:
    pref = db_prefix_from_name(dbname)
    base, ext = _sanitize_filename(original_name)
    pk = f"{pref}{base}.{ext}"
    validate_pk(pk)
    return pk

def validate_pk(pk: str) -> None:
    if not _PK_REGEX.match(pk):
        raise ValueError("PK must match '<digits>_<name>.<lowerext>'.")

# --- Safe paths & final locations ---
def safe_join(base: str, *parts: str) -> str:
    base_path = os.path.realpath(os.path.abspath(base))
    candidate = os.path.realpath(os.path.join(base_path, *parts))

    try:
        is_contained = os.path.commonpath((base_path, candidate)) == base_path
    except ValueError:
        is_contained = False

    if not is_contained:
        raise ValueError("Path traversal not allowed.")
    return candidate

def final_paths(data_dir: str, dbname: str, media_dir: str, pk_name: str) -> Tuple[str, str]:
    base = safe_join(data_dir, dbname, media_dir)
    file_path = safe_join(base, pk_name)
    thumb_dir = safe_join(base, "thumbs")
    thumb_path = safe_join(thumb_dir, f"{pk_name.rsplit('.', 1)[0]}.jpg")
    return file_path, thumb_path

# --- Uploads temp area ---
def save_to_uploads(upload_folder: str, file_storage: FileStorage) -> Tuple[str, int]:
    os.makedirs(upload_folder, exist_ok=True)
    max_bytes = int(getattr(Config, "MAX_UPLOAD_FILE_BYTES", 64 * 1024 * 1024))
    tmp_file = tempfile.NamedTemporaryFile(prefix="upload_", dir=upload_folder, delete=False)
    tmp_path = tmp_file.name
    total = 0
    try:
        file_storage.stream.seek(0)
        with tmp_file:
            while True:
                chunk = file_storage.stream.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > max_bytes:
                    raise ValueError("Uploaded file is too large.")
                tmp_file.write(chunk)
    except Exception:
        cleanup_upload(tmp_path)
        raise
    return tmp_path, total


def read_upload_bytes(file_storage: FileStorage, max_bytes: int | None = None) -> bytes:
    limit = int(max_bytes or getattr(Config, "MAX_TEXT_UPLOAD_BYTES", 8 * 1024 * 1024))
    stream = getattr(file_storage, "stream", file_storage)
    stream.seek(0)
    chunks = []
    total = 0
    while True:
        chunk = stream.read(min(1024 * 1024, limit - total + 1))
        if not chunk:
            return b"".join(chunks)
        chunks.append(chunk)
        total += len(chunk)
        if total > limit:
            raise ValueError("Uploaded file is too large.")

def cleanup_upload(path: str) -> None:
    try:
        if os.path.exists(path):
            os.remove(path)
    except Exception:
        pass

# --- Move & Delete ---
def move_into_place(src_temp: str, dst_final: str) -> None:
    os.makedirs(os.path.dirname(dst_final), exist_ok=True)
    shutil.move(src_temp, dst_final)

def delete_media_files(file_path: str, thumb_path: str) -> Tuple[bool, bool]:
    fd = td = False
    try:
        if os.path.exists(file_path):
            os.remove(file_path); fd = True
    except Exception:
        pass
    try:
        if os.path.exists(thumb_path):
            os.remove(thumb_path); td = True
    except Exception:
        pass
    return fd, td


def delete_media_files_checked(file_path: str, thumb_path: str, *extra_paths: str) -> list[str]:
    failed: list[str] = []
    seen: set[str] = set()
    for path in (file_path, thumb_path, *extra_paths):
        if not path or path in seen:
            continue
        seen.add(path)
        try:
            existed = os.path.exists(path)
            if existed:
                os.remove(path)
        except Exception:
            failed.append(path)
            continue
        if existed and os.path.exists(path):
            failed.append(path)
    return failed

# Public helper: keep extension, return full sanitized name ---
# Return safe filename preserving (lowercased) extension.
# Example: 'My Bad File.JPG' -> 'My_Bad_File.jpg'
def sanitize_filename_keep_ext(name: str) -> str:
    base, ext = _sanitize_filename(name)
    return f"{base}.{ext}"
