from html.parser import HTMLParser

import pytest
from flask import render_template

from app.routes import sections as section_routes


class _Cursor:
    def __init__(self):
        self.query = None

    def __enter__(self):
        return self

    def __exit__(self, _exc_type, _exc, _tb):
        return False

    def execute(self, query, _params=None):
        self.query = query

    def fetchall(self):
        if self.query == "sections-list":
            return [
                (
                    5,
                    "standard",
                    "South face",
                    "5514",
                    "1-4, 7-9",
                    2,
                    [1, 7],
                    [4, 9],
                    [10, 12],
                )
            ]
        if self.query == "authors-list":
            return [("author@example.invalid",)]
        if self.query == "sj-list":
            return [(10,), (11,), (12,)]
        if self.query == "sections-geojson":
            return [
                (
                    5,
                    '{"type":"LineString","coordinates":[[14.1,50.1],[14.2,50.2]]}',
                )
            ]
        return []


class _Connection:
    def cursor(self):
        return _Cursor()

    def close(self):
        return None


def test_sections_page_renders_edit_controls_and_prefill_payload(client, monkeypatch):
    monkeypatch.setattr(section_routes, "get_terrain_connection", lambda _dbname: _Connection())
    monkeypatch.setattr(section_routes, "get_sections_list_sql", lambda: "sections-list")
    monkeypatch.setattr(section_routes, "list_authors_sql", lambda: "authors-list")
    monkeypatch.setattr(section_routes, "list_sj_ids_sql", lambda: "sj-list")

    with client.session_transaction() as session:
        session["selected_db"] = "02_test"

    response = client.get("/sections")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "Existing sections" in html
    assert "border list-panel" in html
    assert 'data-bs-target="#editSectionModal"' in html
    assert 'id="editSectionModal"' in html
    assert 'id="edit-ranges-container"' in html
    assert 'id="editSectionSjs"' in html
    assert 'id="sectionSjs"' in html
    assert html.count("data-su-search-button\n") == 2
    assert html.count("data-su-search-status") == 3
    assert 'data-column="srid"' not in html
    assert 'colspan="7"' in html
    assert "Map view" in html
    assert 'data-bs-target="#modalSectionsMapView"' in html
    assert 'id="sectionsMapView"' in html
    assert 'id="chkSectionsPolygons"' in html
    assert "/sections/geojson" in html

    compact_html = html.replace(" ", "")
    assert '"ranges":[{"from":1,"to":4},{"from":7,"to":9}]' in compact_html
    assert '"sj_ids":[10,12]' in compact_html


def test_sections_geojson_returns_leaflet_ready_lines(client, monkeypatch):
    monkeypatch.setattr(section_routes, "get_terrain_connection", lambda _dbname: _Connection())
    monkeypatch.setattr(section_routes, "sections_lines_geojson_4326_sql", lambda: "sections-geojson")

    with client.session_transaction() as session:
        session["selected_db"] = "02_test"

    response = client.get("/sections/geojson")

    assert response.status_code == 200
    assert response.get_json() == {
        "sections": [
            {
                "id": 5,
                "geojson": {
                    "type": "LineString",
                    "coordinates": [[14.1, 50.1], [14.2, 50.2]],
                },
            }
        ]
    }


class _SuPickerMarkup(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.select = None
        self.selects = {}
        self.inputs = []
        self.ids = []
        self.feed(html)

    def handle_starttag(self, tag, attributes):
        attrs = dict(attributes)
        if "id" in attrs:
            self.ids.append(attrs["id"])
        if tag == "select" and attrs.get("id") in ("sectionSjs", "editSectionSjs"):
            self.select = attrs["id"]
            self.selects[self.select] = {"attrs": attrs, "values": []}
        elif tag == "option" and self.select:
            self.selects[self.select]["values"].append(attrs["value"])
        elif tag == "input" and "data-su-search" in attrs:
            self.inputs.append(attrs)

    def handle_endtag(self, tag):
        if tag == "select":
            self.select = None


@pytest.mark.parametrize("sj_ids", [[], [1, 2, 10, 12, 101]])
def test_section_su_pickers_keep_complete_named_selects_and_unique_controls(app, sj_ids):
    with app.test_request_context():
        html = render_template("sections.html", selected_db="02_test", sections=[], sj_ids=sj_ids,
                               authors=[], open_edit_section_id=None)
    parsed = _SuPickerMarkup(html)
    assert len(parsed.ids) == len(set(parsed.ids))
    assert len(parsed.inputs) == 2
    assert all("name" not in attrs for attrs in parsed.inputs)
    for select_id, size in (("sectionSjs", "14"), ("editSectionSjs", "10")):
        picker = parsed.selects[select_id]
        assert picker["attrs"]["name"] == "ref_sj[]"
        assert "multiple" in picker["attrs"]
        assert picker["attrs"]["size"] == size
        assert picker["values"] == [str(sj_id) for sj_id in sj_ids]
        assert picker["attrs"]["aria-describedby"] == f"{select_id}Status"
        assert f'aria-controls="{select_id}Filter" aria-expanded="false"' in html
