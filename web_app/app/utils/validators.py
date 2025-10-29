# app/utils/validators.py
# utilities for control and validation

import hashlib
from typing import Set

# --- SHA-256 ---
def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()

# --- allowlists ---
def validate_extension(ext: str, allowed: Set[str]) -> None:
    if ext not in allowed:
        raise ValueError("Extension not allowed.")

def validate_mime(mime: str, allowed_mime: Set[str]) -> None:
    if mime not in allowed_mime:
        raise ValueError(f"MIME not allowed: {mime}")

# pattern_check: callable(pk) -> raises on invalid (e.g.. storage.validate_pk)
def validate_pk_name(pk: str, pattern_check) -> None:
    pattern_check(pk)
