from datetime import date
from html.parser import HTMLParser
import json

import pytest
from flask import url_for

from app.routes import su as su_routes


@pytest.mark.parametrize("direct, parents, expected", [
    ([], {}, []),
    (["sonda1"], {"sonda1": "plocha2", "plocha2": "site", "site": None},
     [("sonda1", False), ("plocha2", True), ("site", True)]),
    (["sonda1", "sonda2"], {"sonda1": "plocha", "sonda2": "plocha", "plocha": "site"},
     [("sonda1", False), ("sonda2", False), ("plocha", True), ("site", True)]),
    (["sonda1", "plocha2", "sonda1"], {"sonda1": "plocha2", "plocha2": "site"},
     [("sonda1", False), ("plocha2", False), ("site", True)]),
    (["a"], {"a": "b", "b": "a"}, [("a", False), ("b", True)]),
    (["a", "b"], {"a": "b", "b": "a"}, [("a", False), ("b", False)]),
    (["orphan"], {}, [("orphan", False)]),
])
def test_su_polygon_memberships(direct, parents, expected):
    memberships = su_routes._su_polygon_memberships(direct, parents)
    assert [(item["name"], item["inherited"]) for item in memberships] == expected


def _row(sj_id=7, polygons=None, docs=None):
    row = [None] * 32
    row[:9] = [sj_id, "deposit", "Floor layer", "Occupation", date(2026, 10, 5),
               "author@example.invalid", True, False, "100"]
    row[27:32] = [polygons or [], [], [], [], docs or {}]
    return tuple(row)


class _Connection:
    def __init__(self, rows, parents):
        self.rows = rows
        self.parents = parents
        self.query = None
        self.closed = False

    def cursor(self):
        return self

    def execute(self, query, params=None):
        self.query = query

    def fetchall(self):
        if self.query == "su-table":
            return self.rows
        if self.query == "hierarchy":
            return list(self.parents.items())
        if self.query == "su-media":
            return [(row[0], row[1], row[2]) for row in self.rows]
        return [("author@example.invalid",)]

    def fetchone(self):
        return (len(self.rows),)

    def close(self):
        self.closed = True


def _prepare(client, monkeypatch, rows, parents):
    connection = _Connection(rows, parents)
    monkeypatch.setattr(su_routes, "get_terrain_connection", lambda _dbname: connection)
    monkeypatch.setattr(su_routes, "polygons_hierarchy_sql", lambda: "hierarchy")
    monkeypatch.setattr(su_routes, "list_su_table_sql", lambda: "su-table")
    monkeypatch.setattr(su_routes, "list_su_for_media_select_sql", lambda: "su-media")
    with client.session_transaction() as session:
        session["selected_db"] = "01_SuTest"
    return connection


class _ListMarkup(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.template = None
        self.links = {None: []}
        self.columns = []
        self.payloads = []
        self.feed(html)

    def handle_starttag(self, tag, attributes):
        attrs = dict(attributes)
        if tag == "template":
            self.template = attrs["id"]
            self.links[self.template] = []
        elif tag == "a":
            self.links[self.template].append(attrs.get("href"))
        elif tag == "th" and "data-column" in attrs:
            self.columns.append(attrs["data-column"])
        elif tag == "button" and "data-su" in attrs:
            self.payloads.append(json.loads(attrs["data-su"]))

    def handle_endtag(self, tag):
        if tag == "template":
            self.template = None


@pytest.mark.parametrize("path", ["/add-su", "/add-sj"])
def test_su_list_includes_filtered_inherited_polygons_and_complete_modal(client, monkeypatch, path):
    parents = {"sonda1": "plocha2", "plocha2": "area", "area": 'site <& "4"', 'site <& "4"': None}
    docs = {kind: [f"{kind}_{index}.jpg" for index in range(1, 5)]
            for kind in ("photos", "photograms", "drawings", "sketches")}
    connection = _prepare(client, monkeypatch, [_row(polygons=["sonda1"], docs=docs)], parents)

    response = client.get(path)
    assert response.status_code == 200
    assert connection.closed
    html = response.get_data(as_text=True)
    parsed = _ListMarkup(html)
    assert parsed.columns == ["id", "type", "description", "recorded", "author", "polygon", "documentation"]
    assert html.count("data-column-search\n") == 7
    assert html.count("data-column-sort\n") == 7
    assert 'data-search-value="sonda1, plocha2 (inherited), area (inherited), site &lt;&amp; &#34;4&#34; (inherited)"' in html
    assert 'data-search-value="Photos (photos_1.jpg, photos_2.jpg, photos_3.jpg, photos_4.jpg)' in html
    assert 'data-bs-target="#suItemsModal"' in html
    assert 'id="suNoMatches" hidden' in html
    assert 'js/list_table.js' in html
    assert parsed.payloads[0]["polygon_names"] == ["sonda1"]
    assert len(parsed.payloads[0]["polygon_memberships"]) == 4
    with client.application.test_request_context():
        polygon_urls = [url_for("polygons.polygons", edit_polygon=name) for name in parents]
        assert all(url in parsed.links[None] for url in polygon_urls[:3])
        assert polygon_urls[3] not in parsed.links[None]
        assert parsed.links["su-items-7-polygons"] == polygon_urls
        for kind, endpoint, parameter in (
            ("photos", "photos.serve_photo_file", "id_photo"),
            ("photograms", "photograms.serve_photogram_file", "id_photogram"),
            ("drawings", "drawings.serve_drawing", "id_drawing"),
            ("sketches", "sketches.serve_sketch_file", "id_sketch"),
        ):
            urls = [url_for(endpoint, **{parameter: value}) for value in docs[kind]]
            assert all(url in parsed.links[None] for url in urls[:3])
            assert urls[3] not in parsed.links[None]
            assert parsed.links[f"su-items-7-{kind}"] == urls


def test_su_without_polygons_or_documentation_renders_empty_cells(client, monkeypatch):
    _prepare(client, monkeypatch, [_row()], {})
    response = client.get("/add-sj")
    html = response.get_data(as_text=True)
    assert response.status_code == 200
    assert 'data-items-template="su-items-' not in html
    assert 'data-search-value=""' in html


def test_empty_su_list_renders_without_table(client, monkeypatch):
    _prepare(client, monkeypatch, [], {})
    response = client.get("/add-sj")
    assert response.status_code == 200
    assert "No SUs stored yet." in response.get_data(as_text=True)
    assert 'id="suTable"' not in response.get_data(as_text=True)


def test_su_list_requires_selected_database(client, monkeypatch):
    def unexpected_connection(_dbname):
        pytest.fail("Database guard should run before opening a connection")

    monkeypatch.setattr(su_routes, "get_terrain_connection", unexpected_connection)
    response = client.get("/add-sj")
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/index")
