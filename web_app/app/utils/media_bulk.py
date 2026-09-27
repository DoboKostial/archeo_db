from __future__ import annotations

import os
import re
import tempfile
import zipfile
from datetime import datetime
from typing import Iterable

from config import Config


def _safe_zip_part(value: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", str(value or "").strip()).strip("_")
    return safe or "media"


def _temp_zip_path(media_label: str) -> str:
    upload_dir = getattr(Config, "UPLOAD_FOLDER", "") or ""
    kwargs = {
        "prefix": f"{_safe_zip_part(media_label)}_",
        "suffix": ".zip",
        "delete": False,
    }
    if upload_dir:
        try:
            os.makedirs(upload_dir, exist_ok=True)
            if os.access(upload_dir, os.W_OK):
                kwargs["dir"] = upload_dir
        except Exception:
            pass

    tmp = tempfile.NamedTemporaryFile(**kwargs)
    try:
        return tmp.name
    finally:
        tmp.close()


def build_media_zip(
    selected_db: str,
    media_label: str,
    id_path_pairs: Iterable[tuple[str, str]],
) -> tuple[str, str, int, list[str]]:
    """
    Build a temporary ZIP archive with selected media originals.

    Returns (zip_path, download_name, included_count, missing_ids).
    The caller is responsible for deleting zip_path after send_file finishes.
    """
    label = _safe_zip_part(media_label)
    db_part = _safe_zip_part(selected_db)
    stamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    zip_path = _temp_zip_path(label)
    missing: list[str] = []
    used_names: set[str] = set()
    included = 0

    try:
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, allowZip64=True) as zf:
            for media_id, path in id_path_pairs:
                media_id = str(media_id or "").strip()
                if not media_id or not path or not os.path.exists(path):
                    if media_id:
                        missing.append(media_id)
                    continue

                arc_base = os.path.basename(path)
                arc_name = f"{label}/{arc_base}"
                if arc_name in used_names:
                    root, ext = os.path.splitext(arc_base)
                    arc_name = f"{label}/{root}_{included + 1}{ext}"
                used_names.add(arc_name)

                zf.write(path, arc_name)
                included += 1

        if included == 0:
            raise ValueError("Selected media files are missing on filesystem.")

    except Exception:
        try:
            os.remove(zip_path)
        except Exception:
            pass
        raise

    return zip_path, f"{db_part}_{label}_{stamp}.zip", included, missing
