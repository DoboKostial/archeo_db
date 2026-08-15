from io import BytesIO
from pathlib import Path
import re

from app import queries
from app.routes import geodesy as geodesy_routes


class _Cursor:
    def __init__(self, connection):
        self.connection = connection
        self.rowcount = connection.rowcount

    def __enter__(self):
        return self

    def __exit__(self, _exc_type, _exc, _tb):
        return False

    def execute(self, query, params=None):
        self.connection.executed.append((query, params))
        self.rowcount = self.connection.rowcount

    def fetchone(self):
        if self.connection.fetchone_rows:
            return self.connection.fetchone_rows.pop(0)
        return self.connection.fetchone_row

    def fetchall(self):
        return self.connection.fetchall_rows


class _Connection:
    def __init__(self, fetchone_row=(5514,), fetchone_rows=None, fetchall_rows=None, rowcount=1):
        self.fetchone_row = fetchone_row
        self.fetchone_rows = list(fetchone_rows or [])
        self.fetchall_rows = fetchall_rows or []
        self.rowcount = rowcount
        self.executed = []
        self.committed = False
        self.rolled_back = False

    def cursor(self):
        return _Cursor(self)

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True

    def close(self):
        return None


def _select_test_db(client):
    with client.session_transaction() as session:
        session["selected_db"] = "02_test"


def test_geodesy_page_uses_base_leaflet_only(client, monkeypatch):
    conn = _Connection(fetchone_rows=[(5514,), (42, 99)])
    monkeypatch.setattr(geodesy_routes, "get_terrain_connection", lambda _dbname: conn)

    _select_test_db(client)

    response = client.get("/geodesy")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "Geodesy" in html
    assert "Expected columns" in html
    assert "Points in database" in html
    assert "42" in html
    assert "Last point ID" in html
    assert "99" in html
    assert '<option value="FO">FO</option>' in html
    assert '<option value="FI">FI</option>' in html
    assert '<option value="PR">PR</option>' in html
    assert '<option value="FP">FP</option>' not in html
    assert "Help: Geodesy point import" in html
    assert "Point for precise finds measuring" in html
    assert "Direct profile measuring" in html
    assert 'id="btnModalDownload"' in html
    assert html.count("leaflet@1.9.4") == 2
    assert "/static/js/geodesy_map.js" in html


def test_geodesy_upload_passes_notes_to_upsert(client, monkeypatch):
    conn = _Connection()
    monkeypatch.setattr(geodesy_routes, "get_terrain_connection", lambda _dbname: conn)
    monkeypatch.setattr(geodesy_routes, "upsert_geopt_sql", lambda: "upsert-geopt")

    _select_test_db(client)

    response = client.post(
        "/geodesy/upload",
        data={
            "file": (
                BytesIO(b"id_pts,x,y,h,code,notes\n1,10.5,20.25,30,SU,alpha <b>\n"),
                "points.csv",
            )
        },
        content_type="multipart/form-data",
    )

    assert response.status_code == 302
    assert conn.committed is True
    assert conn.rolled_back is False
    upsert_calls = [call for call in conn.executed if call[0] == "upsert-geopt"]
    assert upsert_calls == [
        (
            "upsert-geopt",
            (10.5, 20.25, 30.0, 5514, 5514, 1, 30.0, "SU", "SU", "SU", "alpha <b>"),
        )
    ]


def test_geodesy_list_ignores_invalid_numeric_filters(client, monkeypatch):
    conn = _Connection(fetchone_row=(1,), fetchall_rows=[(1, 10.0, 20.0, 30.0, "SU", "note")])
    monkeypatch.setattr(geodesy_routes, "get_terrain_connection", lambda _dbname: conn)
    monkeypatch.setattr(geodesy_routes, "count_geopts_sql", lambda: "count-geopts")
    monkeypatch.setattr(geodesy_routes, "list_geopts_sql", lambda: "list-geopts")

    _select_test_db(client)

    response = client.get("/geodesy/list?limit=nope&id_from=bad&id_to=also-bad")
    payload = response.get_json()

    assert response.status_code == 200
    assert payload["ok"] is True
    assert payload["rows"][0]["notes"] == "note"
    assert payload["total"] == 1
    assert payload["page"] == 1
    assert conn.executed == [
        ("count-geopts", (None, None, None, None, None, None, None)),
        ("list-geopts", (None, None, None, None, None, None, None, 25, 0)),
    ]


def test_geodesy_list_uses_server_side_pagination(client, monkeypatch):
    conn = _Connection(fetchone_row=(60,), fetchall_rows=[(26, 1.0, 2.0, 3.0, "FO", None)])
    monkeypatch.setattr(geodesy_routes, "get_terrain_connection", lambda _dbname: conn)
    monkeypatch.setattr(geodesy_routes, "count_geopts_sql", lambda: "count-geopts")
    monkeypatch.setattr(geodesy_routes, "list_geopts_sql", lambda: "list-geopts")

    _select_test_db(client)

    response = client.get("/geodesy/list?page=2&limit=25")
    payload = response.get_json()

    assert response.status_code == 200
    assert payload["page"] == 2
    assert payload["per_page"] == 25
    assert payload["total"] == 60
    assert payload["total_pages"] == 3
    assert conn.executed[-1] == (
        "list-geopts",
        (None, None, None, None, None, None, None, 25, 25),
    )


def test_geodesy_download_exports_all_filtered_points_as_txt(client, monkeypatch):
    conn = _Connection(
        fetchall_rows=[
            (10, 1.25, 2.5, 3.75, "FI", "precise find"),
            (11, 4.0, 5.0, 6.0, "PR", None),
        ]
    )
    monkeypatch.setattr(geodesy_routes, "get_terrain_connection", lambda _dbname: conn)
    monkeypatch.setattr(geodesy_routes, "export_geopts_sql", lambda: "export-geopts")

    _select_test_db(client)

    response = client.get("/geodesy/download?q=find&id_from=10&id_to=20")
    text = response.get_data(as_text=True)

    assert response.status_code == 200
    assert response.mimetype == "text/plain"
    assert "attachment" in response.headers["Content-Disposition"]
    assert "02_test_geodesy_points.txt" in response.headers["Content-Disposition"]
    assert text.splitlines() == [
        "id_pts\tx\ty\th\tcode\tnotes",
        "10\t1.25\t2.5\t3.75\tFI\tprecise find",
        "11\t4.0\t5.0\t6.0\tPR\t",
    ]
    assert conn.executed == [
        ("export-geopts", ("find", "%find%", "%find%", 10, 10, 20, 20)),
    ]


def test_geodesy_ajax_delete_accepts_csrf_header(client, monkeypatch):
    conn = _Connection()
    monkeypatch.setattr(geodesy_routes, "get_terrain_connection", lambda _dbname: conn)
    monkeypatch.setattr(geodesy_routes, "delete_geopt_sql", lambda: "delete-geopt")
    client.application.config["WTF_CSRF_ENABLED"] = True

    _select_test_db(client)

    page = client.get("/geodesy")
    token = re.search(r'name="csrf-token" content="([^"]+)"', page.get_data(as_text=True)).group(1)

    missing_token = client.post("/geodesy/delete/1", headers={"Accept": "application/json"})
    assert missing_token.status_code == 400

    response = client.post(
        "/geodesy/delete/1",
        headers={
            "Accept": "application/json",
            "X-CSRFToken": token,
            "X-Requested-With": "XMLHttpRequest",
        },
    )

    assert response.status_code == 200
    assert response.get_json() == {"ok": True}
    assert conn.committed is True
    assert ("delete-geopt", (1,)) in conn.executed


def test_geodesy_update_returns_not_found_when_no_row_changes(client, monkeypatch):
    conn = _Connection(rowcount=0)
    monkeypatch.setattr(geodesy_routes, "get_terrain_connection", lambda _dbname: conn)
    monkeypatch.setattr(geodesy_routes, "update_geopt_sql", lambda: "update-geopt")

    _select_test_db(client)

    response = client.post(
        "/geodesy/update/999",
        json={"x": 10, "y": 20, "h": 30, "code": "SU", "notes": "missing"},
    )
    payload = response.get_json()

    assert response.status_code == 404
    assert payload == {"ok": False, "error": "Point not found."}
    assert conn.committed is False
    assert conn.rolled_back is True


def test_upsert_geopt_sql_persists_notes_without_clearing_blank_uploads():
    sql = queries.upsert_geopt_sql()

    assert "INSERT INTO tab_geopts (id_pts, x, y, h, code, notes)" in sql
    assert "NULLIF(BTRIM(%s), '')" in sql
    assert "notes = COALESCE(EXCLUDED.notes, tab_geopts.notes)" in sql
    assert "'FO'" in sql
    assert "'FI'" in sql
    assert "'PR'" in sql
    assert "'FP'" not in sql

    update_sql = queries.update_geopt_sql()
    assert "'FO'" in update_sql
    assert "'FI'" in update_sql
    assert "'PR'" in update_sql
    assert "'FP'" not in update_sql

    export_sql = queries.export_geopts_sql()
    assert "ORDER BY id_pts" in export_sql
    assert "LIMIT" not in export_sql


def test_geodesy_map_script_has_single_init_and_safe_table_rendering():
    js_path = Path(__file__).resolve().parents[1] / "app" / "static" / "js" / "geodesy_map.js"
    script = js_path.read_text(encoding="utf-8")

    assert script.count('window.addEventListener("load"') == 1
    assert "escapeHtml" in script
    assert "replaceLayer" in script
    assert "csrfToken" in script
    assert '"X-CSRFToken"' in script
    assert 'credentials: "same-origin"' in script
    assert "modalPageSize = 25" in script
    assert 'byId("btnGeoptsPrev")' in script
    assert 'byId("btnGeoptsNext")' in script
    assert 'FI: "#' in script
    assert 'PR: "#' in script
    assert "limit: 1000" not in script
    assert "tr.innerHTML" not in script
