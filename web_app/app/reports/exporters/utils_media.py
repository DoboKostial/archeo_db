# app/reports/exporters/utils_media.py
from __future__ import annotations

import os
from typing import List

from app.reports.context import ReportContext
from config import Config


MEDIA_KINDS = ("photos", "drawings", "sketches", "photograms")


def media_dir(ctx: ReportContext, kind: str) -> str:
    sub = (Config.MEDIA_DIRS or {}).get(kind, "")
    if not sub:
        return ""
    return os.path.join(Config.DATA_DIR, ctx.selected_db, sub)


def list_files_for_media_id(ctx: ReportContext, kind: str, media_id: str) -> List[str]:
    """
    Return filenames (NOT thumbnails) for media_id in:
      DATA_DIR/<db>/<kind>/
    We list files that start with '<id>.' (any ext).
    """
    base = media_dir(ctx, kind)
    if not base or not os.path.isdir(base):
        return []

    out: List[str] = []
    prefix = f"{media_id}."
    try:
        for fn in os.listdir(base):
            if fn.startswith(prefix):
                out.append(fn)
    except Exception:
        return []

    return sorted(out)