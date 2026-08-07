import io
import os
from types import SimpleNamespace

import pytest

import app as app_package
from app import database
from app.queries import (
    list_photos_sql,
    rebuild_geom_sql,
    report_finds_list_all_sql,
    report_samples_list_all_sql,
)
from app.routes import admin as admin_routes
from app.routes import auth as auth_routes
from app.routes import drawings as drawing_routes
from app.routes import main as main_routes
from app.utils import admin as admin_utils
from config import Config


class _DrawingConnection:
    def __init__(self):
        self.last_query = ""
        self.rolled_back = False
        self.closed = False

    def cursor(self):
        return self

    def execute(self, query, _params=None):
        self.last_query = str(query)

    def fetchone(self):
        if "gloss_personalia" in self.last_query:
            return (1,)
        if "checksum_sha256" in self.last_query:
            return None
        return (1,)

    def commit(self):
        raise RuntimeError("simulated commit failure")

    def rollback(self):
        self.rolled_back = True

    def close(self):
        self.closed = True

    def __enter__(self):
        return self

    def __exit__(self, _exc_type, _exc, _traceback):
        return False


class _AuthConnection:
    def close(self):
        return None


def test_drawing_replacement_restores_original_files_on_rollback(
    client,
    tmp_path,
    monkeypatch,
):
    data_dir = tmp_path / "data"
    upload_dir = tmp_path / "uploads"
    monkeypatch.setattr(Config, "DATA_DIR", str(data_dir))
    monkeypatch.setattr(Config, "UPLOAD_FOLDER", str(upload_dir))

    drawing_id = "01_drawing.pdf"
    final_path, thumb_path = drawing_routes._final_paths("01_SecurityTest", drawing_id)
    os.makedirs(os.path.dirname(final_path), exist_ok=True)
    os.makedirs(os.path.dirname(thumb_path), exist_ok=True)
    with open(final_path, "wb") as file_handle:
        file_handle.write(b"old drawing")
    with open(thumb_path, "wb") as file_handle:
        file_handle.write(b"old thumbnail")

    connection = _DrawingConnection()
    monkeypatch.setattr(drawing_routes, "get_terrain_connection", lambda _dbname: connection)

    with client.session_transaction() as session:
        session["selected_db"] = "01_SecurityTest"

    response = client.post(
        f"/drawings/edit/{drawing_id}",
        data={
            "author": "author@example.invalid",
            "datum": "2026-08-02",
            "file": (io.BytesIO(b"%PDF-1.4 replacement"), "replacement.pdf"),
        },
        content_type="multipart/form-data",
    )

    assert response.status_code == 302
    assert connection.rolled_back is True
    assert connection.closed is True
    with open(final_path, "rb") as file_handle:
        assert file_handle.read() == b"old drawing"
    with open(thumb_path, "rb") as file_handle:
        assert file_handle.read() == b"old thumbnail"
    assert not list(data_dir.rglob("*.replace-*"))
    assert not list(data_dir.rglob("*.backup-*"))


def test_database_connections_use_closing_context_manager(monkeypatch):
    captured = {}

    def fake_connect(**kwargs):
        captured.update(kwargs)
        return kwargs

    monkeypatch.setattr(database.psycopg2, "connect", fake_connect)

    result = database.get_auth_connection()

    assert result["connection_factory"] is database.ClosingConnection


def test_database_backup_uses_terrain_credentials(tmp_path, monkeypatch):
    backup_dir = tmp_path / "backups"
    data_dir = tmp_path / "data"
    terrain_dir = data_dir / "01_Project"
    terrain_dir.mkdir(parents=True)
    (terrain_dir / "note.txt").write_text("content", encoding="utf-8")

    monkeypatch.setattr(Config, "BACKUP_DIR", str(backup_dir))
    monkeypatch.setattr(Config, "DATA_DIR", str(data_dir))
    monkeypatch.setattr(Config, "TERRAIN_DB_HOST", "terrain-host")
    monkeypatch.setattr(Config, "TERRAIN_DB_PORT", 5544)
    monkeypatch.setattr(Config, "TERRAIN_DB_USER", "terrain-user")
    monkeypatch.setattr(Config, "TERRAIN_DB_PASSWORD", "terrain-password")

    captured = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured["env"] = kwargs["env"]
        dump_path = command[command.index("-f") + 1]
        with open(dump_path, "wb") as file_handle:
            file_handle.write(b"database dump")
        return SimpleNamespace(stdout="", stderr="")

    monkeypatch.setattr(database.subprocess, "run", fake_run)

    dump_path, files_path = database.create_database_backup("01_Project")

    command = captured["command"]
    assert command[command.index("-h") + 1] == "terrain-host"
    assert command[command.index("-p") + 1] == "5544"
    assert command[command.index("-U") + 1] == "terrain-user"
    assert captured["env"]["PGPASSWORD"] == "terrain-password"
    assert os.path.exists(dump_path)
    assert os.path.exists(files_path)


def test_downloaded_backup_artifacts_are_removed_on_response_close(
    client,
    tmp_path,
    monkeypatch,
):
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    dump_path = backup_dir / "01_Project_20260802.backup.gz"
    files_path = backup_dir / "01_Project_files_20260802.tar.gz"
    dump_path.write_bytes(b"dump")
    files_path.write_bytes(b"files")

    monkeypatch.setattr(Config, "BACKUP_DIR", str(backup_dir))
    monkeypatch.setattr(
        app_package,
        "get_user_access_state",
        lambda _conn, _email: ("Security Test", "archeolog", True),
    )
    monkeypatch.setattr(admin_routes, "_terrain_database_available", lambda _dbname: True)
    monkeypatch.setattr(
        admin_routes,
        "create_database_backup",
        lambda _dbname: (str(dump_path), str(files_path)),
    )

    response = client.post(
        "/backup-database",
        data={"dbname": "01_Project"},
        buffered=False,
    )
    zip_path = backup_dir / "01_Project_20260802_full_backup.zip"

    assert response.status_code == 200
    assert zip_path.exists()
    response.close()
    assert not dump_path.exists()
    assert not files_path.exists()
    assert not zip_path.exists()


def test_directory_size_is_cached(tmp_path, monkeypatch):
    monkeypatch.setattr(Config, "DIRECTORY_SIZE_CACHE_SECONDS", 300, raising=False)
    main_routes._DIRECTORY_SIZE_CACHE.clear()
    (tmp_path / "first.bin").write_bytes(b"1234")

    first = main_routes._directory_size_bytes(str(tmp_path))
    (tmp_path / "second.bin").write_bytes(b"56789")
    cached = main_routes._directory_size_bytes(str(tmp_path))
    main_routes._DIRECTORY_SIZE_CACHE.clear()
    refreshed = main_routes._directory_size_bytes(str(tmp_path))

    assert first == 4
    assert cached == 4
    assert refreshed == 9


def test_home_renders_database_selection_flash_once(client, monkeypatch):
    class IndexCursor:
        def __init__(self):
            self.query = ""

        def execute(self, query):
            self.query = query

        def fetchone(self):
            return ("PostgreSQL test",)

        def fetchall(self):
            return []

        def close(self):
            return None

    class IndexConnection:
        def cursor(self):
            return IndexCursor()

        def close(self):
            return None

    monkeypatch.setattr(main_routes, "get_auth_connection", IndexConnection)
    monkeypatch.setattr(main_routes, "get_terrain_db_list", lambda _conn: ["01_Project"])
    monkeypatch.setattr(
        main_routes,
        "get_user_name_and_last_login",
        lambda _conn, _email: ("Security Test", None),
    )

    response = client.post(
        "/select-db",
        data={"selected_db": "01_Project"},
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert response.get_data(as_text=True).count("was chosen ---&gt;") == 1


def test_photo_list_query_includes_link_counts():
    query = list_photos_sql()

    for alias in ("sj_count", "polygon_count", "section_count", "find_count", "sample_count"):
        assert alias in query


def test_report_queries_include_media_arrays():
    assert "AS photo_ids" in report_finds_list_all_sql()
    assert "AS sketch_ids" in report_finds_list_all_sql()
    assert "AS photo_ids" in report_samples_list_all_sql()
    assert "AS sketch_ids" in report_samples_list_all_sql()


def test_polygon_rebuild_sql_falls_back_to_outer_hull():
    query = rebuild_geom_sql()

    assert "ST_IsSimple" in query
    assert "ST_ConvexHull" in query
    assert "ST_Collect" in query


def test_password_reset_response_does_not_enumerate_accounts(app, monkeypatch):
    auth_routes._RATE_LIMIT_BUCKETS.clear()
    monkeypatch.setattr(auth_routes, "get_auth_connection", lambda: _AuthConnection())
    monkeypatch.setattr(auth_routes, "get_enabled_user_name_by_email", lambda _conn, _email: None)

    response = app.test_client().post(
        "/forgot-password",
        json={"email": "missing@example.invalid"},
    )

    assert response.status_code == 200
    assert response.get_json()["success"] is True


@pytest.mark.parametrize("path", ("/login", "/forgot-password"))
def test_public_auth_posts_require_csrf(app, path):
    app.config["WTF_CSRF_ENABLED"] = True

    response = app.test_client().post(path, data={})

    assert response.status_code == 400


def test_password_reset_url_uses_configured_base_url(app, monkeypatch):
    auth_routes._RATE_LIMIT_BUCKETS.clear()
    app.config["BASE_URL"] = "https://trusted.example"
    monkeypatch.setattr(auth_routes, "get_auth_connection", lambda: _AuthConnection())
    monkeypatch.setattr(auth_routes, "get_enabled_user_name_by_email", lambda _conn, _email: "User")
    monkeypatch.setattr(auth_routes, "get_user_password_hash", lambda _conn, _email: "hash")
    sent = {}
    monkeypatch.setattr(
        auth_routes,
        "send_password_reset_email",
        lambda _email, _name, reset_url: sent.update(reset_url=reset_url),
    )

    response = app.test_client().post(
        "/forgot-password",
        json={"email": "user@example.invalid"},
        headers={"Host": "attacker.example"},
    )

    assert response.status_code == 200
    assert sent["reset_url"].startswith("https://trusted.example/forgot-password?token=")
    assert "attacker.example" not in sent["reset_url"]


def test_account_email_base_url_ignores_request_host(app):
    app.config["BASE_URL"] = "https://trusted.example"

    with app.test_request_context(headers={"Host": "attacker.example"}):
        base_url = admin_utils._get_base_url()

    assert base_url == "https://trusted.example"


@pytest.mark.parametrize(
    "target",
    (
        "https://attacker.example",
        "//attacker.example/path",
        "/\\attacker.example/path",
        "/%2f%2fattacker.example/path",
        "javascript:alert(1)",
    ),
)
def test_login_rejects_external_next_urls(target):
    assert auth_routes._safe_next_url(target) is None
