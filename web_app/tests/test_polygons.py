from html.parser import HTMLParser

import pytest
from flask import url_for

from app.routes import polygons as polygon_routes


class _Connection:
    def __init__(self, rows):
        self.rows = rows
        self.query = None
        self.closed = False

    def cursor(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, query):
        self.query = query

    def fetchall(self):
        return self.rows if self.query == "polygons-list" else [("author@example.invalid",)]

    def close(self):
        self.closed = True


def _prepare(client, monkeypatch, rows):
    connection = _Connection(rows)
    monkeypatch.setattr(polygon_routes, "get_terrain_connection", lambda _dbname: connection)
    monkeypatch.setattr(polygon_routes, "get_polygons_list", lambda: "polygons-list")
    monkeypatch.setattr(polygon_routes, "list_authors_sql", lambda: "authors-list")
    with client.session_transaction() as session:
        session["selected_db"] = "01_PolygonTest"
    return connection


def test_polygons_list_links_sus_and_exposes_all_documentation_to_filters(client, monkeypatch):
    docs = {"photos": ["01.jpg", "02.jpg", "03.jpg", "04.jpg"], "photograms": [], "sketches": []}
    connection = _prepare(client, monkeypatch, [
        (1, "Trench 2", 10, 5514, None, "research_phase", True, False, "", [], [], docs, [2, 11, 42]),
    ])

    response = client.get("/polygons")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert connection.closed
    assert 'Define polygon manualy' in html
    for side in ('top', 'bottom'):
        assert f'name="{side}_range_from[]"' in html
        assert f'name="{side}_range_to[]"' in html
    assert 'TOP (upper polygon) point ranges (FROM–TO)' in html
    assert 'BOTTOM (lower polygon) point ranges (FROM–TO)' in html
    assert 'Point ranges are optional.' in html
    assert 'Enter at least one TOP or BOTTOM range' not in html
    assert 'at least one side is required' not in html
    assert 'id="replaceManualGeometry"' in html
    assert "SRID / EPSG" not in html
    assert 'data-column="sus"' in html
    with client.application.test_request_context():
        for su in (2, 11, 42):
            assert f'href="{url_for("su.add_su", edit_su=su)}"' in html
    assert 'data-search-value="Photos (01.jpg, 02.jpg, 03.jpg, 04.jpg)' in html
    assert html.count("data-column-search\n") == 9
    assert html.count("data-column-sort\n") == 9
    assert 'data-bs-target="#editPolygonModal"' in html
    assert 'data-bs-target="#deletePolygonModal"' in html


def test_polygons_without_sus_render_empty_cell_and_pagination(client, monkeypatch):
    _prepare(client, monkeypatch, [
        (1, "Empty trench", 0, None, None, "other", False, False, "", [], [], {}, []),
    ])

    response = client.get("/polygons")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert 'edit_su=' not in html
    assert 'id="polygonsPagination"' in html
    assert 'id="polygonsNoMatches" hidden' in html


class _ItemLists(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.template = None
        self.links = {None: []}
        self.buttons = {}
        self.feed(html)

    def handle_starttag(self, tag, attributes):
        attrs = dict(attributes)
        if tag == "template":
            self.template = attrs["id"]
            self.links[self.template] = []
        elif tag == "a":
            self.links[self.template].append(attrs.get("href"))
        elif tag == "button" and "data-items-template" in attrs:
            self.buttons[attrs["data-items-template"]] = attrs

    def handle_endtag(self, tag):
        if tag == "template":
            self.template = None


@pytest.mark.parametrize("count", [3, 4, 10, 11, 15])
def test_polygon_cells_respect_link_limits_and_offer_complete_modal_lists(client, monkeypatch, count):
    docs = {kind: [f"{kind}_{index:02}.jpg" for index in range(1, count + 1)]
            for kind in ("photos", "photograms", "sketches")}
    sus = list(range(1, count + 1))
    polygon_name = 'Trench <& "2"'
    _prepare(client, monkeypatch, [
        (1, polygon_name, 10, 5514, None, "research_phase", True, False, "", [], [], docs, sus),
    ])

    response = client.get("/polygons")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    parsed = _ItemLists(html)
    endpoints = {
        "sus": ("su.add_su", "edit_su", "SUs", sus),
        "photos": ("photos.serve_photo_file", "id_photo", "Photos", docs["photos"]),
        "photograms": ("photograms.serve_photogram_file", "id_photogram", "Photograms", docs["photograms"]),
        "sketches": ("sketches.serve_sketch_file", "id_sketch", "Sketches", docs["sketches"]),
    }
    with client.application.test_request_context():
        for kind, (endpoint, parameter, label, values) in endpoints.items():
            limit = 10 if kind == "sus" else 3
            urls = [url_for(endpoint, **{parameter: value}) for value in values]
            assert all(url in parsed.links[None] for url in urls[:limit])
            assert all(url not in parsed.links[None] for url in urls[limit:])
            template_id = f"polygon-items-1-{kind}"
            if count > limit:
                assert parsed.links[template_id] == urls
                assert parsed.buttons[template_id]["data-bs-target"] == "#polygonItemsModal"
                assert parsed.buttons[template_id]["data-items-title"] == f"{label}: {polygon_name} ({count})"
                assert f">+{count - limit}</button>" in html
            else:
                assert template_id not in parsed.buttons
                assert template_id not in parsed.links


def test_empty_polygons_list_renders_without_table_controls(client, monkeypatch):
    _prepare(client, monkeypatch, [])

    response = client.get("/polygons")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "No polygons stored yet." in html
    assert 'id="polygonsTable"' not in html
