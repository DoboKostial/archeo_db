"""Resolve the stored gallery thumbnails used in PDF reports."""

import os

from app.reports.context import ReportContext
from app.utils.storage import final_paths, safe_join
from config import Config


def find_thumbnail(ctx: ReportContext, kind: str, media_id: str) -> str:
    subdir = (Config.MEDIA_DIRS or {}).get(kind, "")
    mid = str(media_id).strip() if media_id is not None else ""
    if not subdir or not mid:
        return ""

    try:
        # Uploads replace the original extension with .jpg for every thumbnail.
        _, canonical = final_paths(Config.DATA_DIR, ctx.selected_db, subdir, mid)
        thumb_dir = os.path.dirname(canonical)
        candidates = [canonical]
        # Retain support for older thumbnail names, including full media IDs.
        candidates.extend(
            safe_join(thumb_dir, mid + ext)
            for ext in (".jpg", ".jpeg", ".png", ".webp", ".tiff")
        )
        candidates.append(safe_join(thumb_dir, mid))
    except ValueError:
        return ""

    for path in dict.fromkeys(candidates):
        if os.path.isfile(path):
            return path
    return ""
