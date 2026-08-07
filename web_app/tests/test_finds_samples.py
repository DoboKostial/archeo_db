from app.routes import finds_samples as finds_samples_routes


class _Cursor:
    def __init__(self):
        self.query = None
        self.params = None

    def __enter__(self):
        return self

    def __exit__(self, _exc_type, _exc, _tb):
        return False

    def execute(self, query, _params=None):
        self.query = query
        self.params = _params

    def fetchone(self):
        if self.query == "find-count":
            return (12,)
        if self.query == "sample-count":
            return (11,)
        return None

    def fetchall(self):
        if self.query == "find-types":
            return [("pottery",), ("bone",)]
        if self.query == "sample-types":
            return [("soil",)]
        if self.query == "polygons":
            return [("P1",)]
        if self.query == "finds":
            limit, offset = self.params or (30, 0)
            rows = [
                (idx, "pottery", 7, 1, 3, "P1", None, f"find {idx}")
                for idx in range(12, 0, -1)
            ]
            return rows[offset:offset + limit]
        if self.query == "samples":
            limit, offset = self.params or (30, 0)
            rows = [
                (idx, "soil", 7, "P1", None, f"sample {idx}")
                for idx in range(11, 0, -1)
            ]
            return rows[offset:offset + limit]
        return []


class _Connection:
    def cursor(self):
        return _Cursor()

    def close(self):
        return None


def test_finds_samples_page_uses_neutral_work_surface(client, monkeypatch):
    monkeypatch.setattr(finds_samples_routes, "get_terrain_connection", lambda _dbname: _Connection())
    monkeypatch.setattr(finds_samples_routes, "list_find_types_sql", lambda: "find-types")
    monkeypatch.setattr(finds_samples_routes, "list_sample_types_sql", lambda: "sample-types")
    monkeypatch.setattr(finds_samples_routes, "list_polygons_names_sql", lambda: "polygons")
    monkeypatch.setattr(finds_samples_routes, "list_finds_sql", lambda: "finds")
    monkeypatch.setattr(finds_samples_routes, "list_samples_sql", lambda: "samples")

    with client.session_transaction() as session:
        session["selected_db"] = "02_test"

    response = client.get("/finds-samples")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "finds-samples-page" in html
    assert "finds-samples-pane finds-pane" in html
    assert "finds-samples-pane samples-pane" in html
    assert "card fs-panel" in html
    assert "fs-list-panel list-panel" in html
    assert "fs-panel-header" in html
    assert "table-bordered table-hover" in html
    assert "Existing finds" in html
    assert "Existing samples" in html
    assert "findsPaginationWrap" in html
    assert "samplesPaginationWrap" in html
    assert "findsPagination" in html
    assert "samplesPagination" in html
    assert "Save find" in html
    assert "Save sample" in html
    assert "btn btn-dark" in html
    assert "btn-outline-dark" in html
    assert "Last finds" not in html
    assert "Last samples" not in html
    assert "bg-primary-subtle" not in html
    assert "bg-success-subtle" not in html
    assert "border-primary" not in html
    assert "border-success" not in html
    assert "btn-primary" not in html
    assert "btn-success" not in html


def test_finds_samples_list_endpoints_return_page_metadata(client, monkeypatch):
    monkeypatch.setattr(finds_samples_routes, "get_terrain_connection", lambda _dbname: _Connection())
    monkeypatch.setattr(finds_samples_routes, "count_finds_sql", lambda: "find-count")
    monkeypatch.setattr(finds_samples_routes, "count_samples_sql", lambda: "sample-count")
    monkeypatch.setattr(finds_samples_routes, "list_finds_sql", lambda: "finds")
    monkeypatch.setattr(finds_samples_routes, "list_samples_sql", lambda: "samples")

    with client.session_transaction() as session:
        session["selected_db"] = "02_test"

    finds_response = client.get("/finds-samples/find/list?limit=10&offset=10")
    finds_json = finds_response.get_json()

    assert finds_response.status_code == 200
    assert finds_json["total"] == 12
    assert finds_json["limit"] == 10
    assert finds_json["offset"] == 10
    assert [row["id_find"] for row in finds_json["rows"]] == [2, 1]

    samples_response = client.get("/finds-samples/sample/list?limit=10&offset=10")
    samples_json = samples_response.get_json()

    assert samples_response.status_code == 200
    assert samples_json["total"] == 11
    assert samples_json["limit"] == 10
    assert samples_json["offset"] == 10
    assert [row["id_sample"] for row in samples_json["rows"]] == [1]
