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

    Supports both patterns:
      1) media_id is an ID prefix (e.g. "123") -> matches "123.*", "123_*", "123-*"
      2) media_id is already a filename (e.g. "111_photo03.jpg") -> returns it if exists
    """
    base = media_dir(ctx, kind)
    if not base or not os.path.isdir(base):
        return []

    mid = (str(media_id) or "").strip()
    if not mid:
        return []

    # 1) If mid looks like a filename (has an extension), return it if present
    if "." in mid:
        p = os.path.join(base, mid)
        if os.path.isfile(p):
            return [mid]
        # sometimes case differs; fallback to scan
        # (still continue to prefix scan below)

    out: List[str] = []
    try:
        for fn in os.listdir(base):
            # ignore thumbs folder and other directories
            if fn == "thumbs":
                continue
            full = os.path.join(base, fn)
            if not os.path.isfile(full):
                continue

            if fn.startswith(mid + ".") or fn.startswith(mid + "_") or fn.startswith(mid + "-") or fn == mid:
                out.append(fn)
    except Exception:
        return []

    return sorted(set(out))