import ast
import io
from pathlib import Path

import pytest
from werkzeug.datastructures import FileStorage

import app as app_package
from app.routes import auth as auth_routes
from app.routes import finds_samples as finds_samples_routes
from app.routes import main as main_routes
from app.utils.storage import final_paths, safe_join, save_to_uploads
from app.utils.tokens import (
    create_password_reset_token,
    password_reset_token_matches,
    decode_password_reset_token,
)
from app.utils.validators import validate_extension, validate_mime


class _FakeConnection:
    def __init__(self, row=None):
        self.row = row
        self.closed = False

    def cursor(self):
        return self

    def execute(self, _query, _params=None):
        return None

    def fetchone(self):
        return self.row

    def close(self):
        self.closed = True

    def __enter__(self):
        return self

    def __exit__(self, _exc_type, _exc, _traceback):
        return False


def _select_database(client, dbname="01_SecurityTest"):
    with client.session_transaction() as session:
        session["selected_db"] = dbname


def test_safe_join_rejects_paths_outside_storage_root(tmp_path):
    root = tmp_path / "data"
    root.mkdir()

    with pytest.raises(ValueError, match="Path traversal"):
        safe_join(str(root), "..", "secret.txt")

    with pytest.raises(ValueError, match="Path traversal"):
        safe_join(str(root), "/etc/passwd")

    with pytest.raises(ValueError, match="Path traversal"):
        final_paths(str(root), "/tmp", "photos", "01_photo.jpg")


def test_safe_join_rejects_symlink_escape(tmp_path):
    root = tmp_path / "data"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    (root / "linked").symlink_to(outside, target_is_directory=True)

    with pytest.raises(ValueError, match="Path traversal"):
        safe_join(str(root), "linked", "secret.txt")


def test_photo_route_rejects_traversal(client):
    _select_database(client)

    response = client.get("/photos/file/..%2F..%2F..%2Fetc%2Fpasswd")

    assert response.status_code == 404
    assert b"root:" not in response.data


def test_selected_database_guard_discards_invalid_session_value(client):
    _select_database(client, "../../tmp")

    response = client.get("/photos/file/01_photo.jpg")

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/index")
    with client.session_transaction() as session:
        assert "selected_db" not in session


def test_select_database_requires_available_database(client, monkeypatch):
    connection = _FakeConnection()
    monkeypatch.setattr(main_routes, "get_auth_connection", lambda: connection)
    monkeypatch.setattr(main_routes, "get_terrain_db_list", lambda _conn: ["01_Allowed"])

    response = client.post("/select-db", data={"selected_db": "01_NotAvailable"})

    assert response.status_code == 302
    assert connection.closed is True
    with client.session_transaction() as session:
        assert "selected_db" not in session


def test_select_database_accepts_available_database(client, monkeypatch):
    connection = _FakeConnection()
    monkeypatch.setattr(main_routes, "get_auth_connection", lambda: connection)
    monkeypatch.setattr(main_routes, "get_terrain_db_list", lambda _conn: ["01_Allowed"])

    response = client.post("/select-db", data={"selected_db": "01_Allowed"})

    assert response.status_code == 302
    assert connection.closed is True
    with client.session_transaction() as session:
        assert session["selected_db"] == "01_Allowed"


@pytest.mark.parametrize(
    ("path", "row"),
    (
        (
            "/finds-samples/find/7",
            (7, "<img src=x onerror=alert(1)>", 12, 1, 2, None, None, "<script>alert(1)</script>"),
        ),
        (
            "/finds-samples/sample/8",
            (8, "<img src=x onerror=alert(1)>", 12, None, None, "<script>alert(1)</script>"),
        ),
    ),
)
def test_find_and_sample_details_escape_database_values(client, monkeypatch, path, row):
    _select_database(client)
    monkeypatch.setattr(
        finds_samples_routes,
        "get_terrain_connection",
        lambda _dbname: _FakeConnection(row),
    )

    response = client.get(path)
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "<img src=x onerror=alert(1)>" not in html
    assert "<script>alert(1)</script>" not in html
    assert "&lt;img src=x onerror=alert(1)&gt;" in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html


def test_password_reset_token_cannot_authenticate_as_session(client):
    reset_token = create_password_reset_token(
        "security-test@example.invalid",
        "current-password-hash",
        lifetime_minutes=5,
    )
    client.set_cookie("token", reset_token)

    response = client.get("/mobile-api-qr.svg")

    assert response.status_code == 302
    assert response.headers["Location"].startswith("/login")


def test_disabled_user_is_rejected_on_each_request(client, monkeypatch):
    monkeypatch.setattr(
        app_package,
        "get_user_access_state",
        lambda _conn, _email: ("Security Test", "tester", False),
    )

    response = client.get("/mobile-api-qr.svg")

    assert response.status_code == 302
    assert response.headers["Location"].startswith("/login")
    assert "token=;" in response.headers.get("Set-Cookie", "")


def test_password_reset_token_is_bound_to_current_password_hash():
    token = create_password_reset_token("user@example.invalid", "old-hash", lifetime_minutes=5)
    payload = decode_password_reset_token(token)

    assert password_reset_token_matches(payload, "old-hash") is True
    assert password_reset_token_matches(payload, "new-hash") is False


def test_password_policy_rejects_weak_passwords():
    assert auth_routes._password_error("short") is not None
    assert auth_routes._password_error("alllowercase123") is not None
    assert auth_routes._password_error("StrongPassword123") is None


def test_svg_is_rejected_even_if_configuration_allows_it():
    with pytest.raises(ValueError, match="Extension not allowed"):
        validate_extension("svg", {"svg"})
    with pytest.raises(ValueError, match="MIME not allowed"):
        validate_mime("image/svg+xml", {"image/svg+xml"})


def test_upload_is_streamed_and_removed_when_file_limit_is_exceeded(tmp_path, monkeypatch):
    monkeypatch.setattr("app.utils.storage.Config.MAX_UPLOAD_FILE_BYTES", 4, raising=False)
    upload = FileStorage(stream=io.BytesIO(b"12345"), filename="large.bin")

    with pytest.raises(ValueError, match="too large"):
        save_to_uploads(str(tmp_path), upload)

    assert list(tmp_path.iterdir()) == []


def test_queries_module_has_no_duplicate_top_level_functions():
    query_path = Path(app_package.__file__).with_name("queries.py")
    tree = ast.parse(query_path.read_text(encoding="utf-8"))
    names = [node.name for node in tree.body if isinstance(node, ast.FunctionDef)]

    assert len(names) == len(set(names))


def test_queries_import_resolves_to_canonical_module():
    import app.queries as queries

    assert Path(queries.__file__).name == "queries.py"
