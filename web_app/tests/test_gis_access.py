from werkzeug.security import generate_password_hash

from app.routes import auth as auth_routes


class _AuthConnection:
    def __init__(self, gis_enabled=True):
        self.gis_enabled = gis_enabled
        self.executions = []
        self.committed = False
        self.closed = False

    def cursor(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, query, params=None):
        self.executions.append((query, params))

    def fetchone(self):
        return (self.gis_enabled,)

    def commit(self):
        self.committed = True

    def rollback(self):
        return None

    def close(self):
        self.closed = True


def test_gis_password_change_requires_current_app_password(client, monkeypatch):
    auth_routes._RATE_LIMIT_BUCKETS.clear()
    conn = _AuthConnection()
    monkeypatch.setattr(auth_routes, "get_auth_connection", lambda: conn)
    monkeypatch.setattr(
        auth_routes,
        "get_user_password_hash",
        lambda _conn, _mail: generate_password_hash("CurrentApp123"),
    )

    response = client.post(
        "/profile/gis-password",
        json={
            "app_password": "wrong",
            "new_password": "NewGisPassword123",
            "confirm_password": "NewGisPassword123",
        },
    )

    assert response.status_code == 403
    assert len(conn.executions) == 1
    assert not conn.committed


def test_gis_password_change_calls_db_function_for_current_user(client, monkeypatch):
    auth_routes._RATE_LIMIT_BUCKETS.clear()
    conn = _AuthConnection()
    monkeypatch.setattr(auth_routes, "get_auth_connection", lambda: conn)
    monkeypatch.setattr(
        auth_routes,
        "get_user_password_hash",
        lambda _conn, _mail: generate_password_hash("CurrentApp123"),
    )

    response = client.post(
        "/profile/gis-password",
        json={
            "app_password": "CurrentApp123",
            "new_password": "NewGisPassword123",
            "confirm_password": "NewGisPassword123",
        },
    )

    assert response.status_code == 200
    assert conn.executions[-1][1] == ("security-test@example.invalid", "NewGisPassword123")
    assert conn.committed and conn.closed
