from flask import Blueprint, g, jsonify

from app.database import auth_connection
from app.auth_tokens import require_mobile_token
from app.responses import _json_error

projects_bp = Blueprint("projects", __name__)


@projects_bp.get("/api/mobile/projects")
@require_mobile_token
def list_projects():
    claims = g.mobile_claims

    try:
        with auth_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT datname
                    FROM pg_database
                    WHERE datallowconn = true
                      AND datistemplate = false
                      AND datname <> 'postgres'
                      AND datname <> 'auth_db'
                      AND datname NOT LIKE 'template%%'
                    ORDER BY datname
                    """
                )
                rows = cur.fetchall()

        return jsonify(
            {
                "projects": [{"name": row[0]} for row in rows],
                "last_project": None,
                "user": {
                    "email": claims.get("email"),
                    "name": claims.get("name"),
                    "role": claims.get("role"),
                },
            }
        )

    except Exception:
        return _json_error("Internal server error.", 500)
