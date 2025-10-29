# app/utils/storage.py
# handlers for storage and paths manipulation

import os
import re
import time
import shutil
from typing import Tuple
from werkzeug.datastructures import FileStorage

# --- PK building & validation ---
_PK_REGEX = re.compile(r"^[0-9]+_[A-Za-z0-9._-]+\.[a-z0-9]+$")

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
def safe_join(*parts: str) -> str:
    for p in parts:
        if ".." in p.split(os.sep):
            raise ValueError("Path traversal not allowed.")
    path = os.path.join(*parts)
    return os.path.normpath(path)

def final_paths(data_dir: str, dbname: str, media_dir: str, pk_name: str) -> Tuple[str, str]:
    base = safe_join(data_dir, dbname, media_dir)
    file_path = safe_join(base, pk_name)
    thumb_dir = safe_join(base, "thumbs")
    thumb_path = safe_join(thumb_dir, f"{pk_name.rsplit('.', 1)[0]}.jpg")
    return file_path, thumb_path

# --- Uploads temp area ---
def save_to_uploads(upload_folder: str, file_storage: FileStorage) -> Tuple[str, int]:
    os.makedirs(upload_folder, exist_ok=True)
    tmp_name = f"tmp_{int(time.time()*1000)}_{os.getpid()}"
    tmp_path = os.path.join(upload_folder, tmp_name)
    file_storage.stream.seek(0)
    with open(tmp_path, "wb") as f:
        f.write(file_storage.stream.read())
    return tmp_path, os.path.getsize(tmp_path)

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
