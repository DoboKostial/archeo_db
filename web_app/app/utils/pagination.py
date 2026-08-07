from __future__ import annotations

from flask import request, url_for


GALLERY_PER_PAGE = 16


def positive_int(value: object, default: int = 1) -> int:
    try:
        parsed = int(str(value).strip())
    except Exception:
        return default
    return parsed if parsed > 0 else default


def gallery_page_args(page_value: object) -> tuple[int, int, int]:
    page = positive_int(page_value, 1)
    per_page = GALLERY_PER_PAGE
    return page, per_page, (page - 1) * per_page


def search_page_args(
    page_value: object,
    limit_value: object,
    *,
    default_limit: int = 20,
    max_limit: int = 50,
) -> tuple[int, int, int]:
    page = positive_int(page_value, 1)
    limit = positive_int(limit_value, default_limit)
    limit = min(limit, max_limit)
    return page, limit, (page - 1) * limit


def page_url(endpoint: str, page: int) -> str:
    args = {}
    for key, values in request.args.lists():
        if key in {"page", "per_page"}:
            continue
        args[key] = values
    args["page"] = page
    return url_for(endpoint, **args)
