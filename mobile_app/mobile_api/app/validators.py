import re

from app.responses import _json_error

TERRAIN_DB_NAME_RE = re.compile(r"^[A-Za-z0-9_]{1,63}$")


def _validate_terrain_db(terrain_db: str):
    if (
        not terrain_db
        or not TERRAIN_DB_NAME_RE.fullmatch(terrain_db)
        or terrain_db in {"postgres", "auth_db"}
        or terrain_db.startswith("template")
    ):
        return _json_error("Invalid terrain database.", 400)
    return None
