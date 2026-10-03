import app as app_package
from app.routes import admin as admin_routes


class _EditUserConnection:
    def __init__(self, user_row=("Old Name", "analyst")):
        self.user_row = user_row
        self.executions = []
        self.committed = False
        self.rolled_back = False
        self.closed = False

    def cursor(self):
        return self

    def execute(self, query, params=None):
        self.executions.append((str(query), params))

    def fetchone(self):
        return self.user_row

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True

    def close(self):
        self.closed = True


def _set_current_role(monkeypatch, role):
    monkeypatch.setattr(
        app_package,
        "get_user_access_state",
        lambda _conn, _email: ("Current User", role, True),
    )


def test_archeolog_can_edit_user_name_and_role(client, monkeypatch):
    _set_current_role(monkeypatch, "archeolog")
    connection = _EditUserConnection()
    synchronized = []
    monkeypatch.setattr(admin_routes, "get_auth_connection", lambda: connection)
    monkeypatch.setattr(
        admin_routes,
        "sync_user_profile_to_all_terrain_dbs",
        lambda mail, name, role: synchronized.append((mail, name, role)) or True,
    )

    response = client.post(
        "/edit-user",
        data={
            "mail": "user@example.invalid",
            "name": "Updated User",
            "group_role": "documentator",
        },
    )

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/admin")
    assert connection.executions[-1][1] == (
        "Updated User",
        "documentator",
        "user@example.invalid",
    )
    assert connection.committed is True
    assert connection.closed is True
    assert synchronized == [
        ("user@example.invalid", "Updated User", "documentator"),
    ]


def test_edit_user_rejects_role_outside_allowlist(client, monkeypatch):
    _set_current_role(monkeypatch, "archeolog")
    route_connection_requested = False

    def unexpected_connection():
        nonlocal route_connection_requested
        route_connection_requested = True
        raise AssertionError("Invalid role must be rejected before opening the route DB connection")

    monkeypatch.setattr(admin_routes, "get_auth_connection", unexpected_connection)

    response = client.post(
        "/edit-user",
        data={
            "mail": "user@example.invalid",
            "name": "Updated User",
            "group_role": "superuser",
        },
    )

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/admin")
    assert route_connection_requested is False
    with client.session_transaction() as session:
        assert ("danger", "Invalid user role.") in session["_flashes"]


def test_non_archeolog_cannot_edit_users(client, monkeypatch):
    _set_current_role(monkeypatch, "documentator")
    route_connection_requested = False

    def unexpected_connection():
        nonlocal route_connection_requested
        route_connection_requested = True
        raise AssertionError("Non-archeolog must be rejected before entering the route")

    monkeypatch.setattr(admin_routes, "get_auth_connection", unexpected_connection)

    response = client.post(
        "/edit-user",
        data={
            "mail": "user@example.invalid",
            "name": "Updated User",
            "group_role": "analyst",
        },
    )

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/index")
    assert route_connection_requested is False


def test_admin_user_roles_match_existing_role_vocabulary():
    assert admin_routes.USER_ROLES == ("archeolog", "documentator", "analyst")


class _GisAccessConnection:
    def __init__(self):
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
        return (True,)

    def commit(self):
        self.committed = True

    def rollback(self):
        return None

    def close(self):
        self.closed = True


def test_archeolog_can_grant_gis_access(client, monkeypatch):
    _set_current_role(monkeypatch, "archeolog")
    conn = _GisAccessConnection()
    monkeypatch.setattr(admin_routes, "get_auth_connection", lambda: conn)

    response = client.post(
        "/admin/gis-access",
        data={"mail": "user@example.invalid", "action": "grant"},
    )

    assert response.status_code == 302
    assert conn.executions[0][1] == (True, "user@example.invalid")
    assert conn.committed and conn.closed


def test_non_archeolog_cannot_change_gis_access(client, monkeypatch):
    _set_current_role(monkeypatch, "analyst")
    monkeypatch.setattr(
        admin_routes, "get_auth_connection",
        lambda: (_ for _ in ()).throw(AssertionError("Must not open DB connection")),
    )

    response = client.post(
        "/admin/gis-access",
        data={"mail": "user@example.invalid", "action": "grant"},
    )

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/index")
