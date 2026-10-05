from html.parser import HTMLParser
import json

import pytest
from flask import url_for

from app.routes import archeo_objects as object_routes
from app.routes import sections as section_routes


class _Connection:
    def __init__(self, rows, sus):
        self.rows = rows
        self.sus = sus
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
        if self.query == "sections-list":
            return self.rows
        if self.query == "authors-list":
            return [("author@example.invalid",)]
        return [(sj_id,) for sj_id in self.sus]

    def close(self):
        self.closed = True


def _prepare(client, monkeypatch, kind, sus, docs, empty=False):
    rows = [] if empty else [(5, "standard", "South face", "5514", "1-4", len(sus), [1], [4], sus, docs)]
    connection = _Connection(rows, sus)
    if kind == "objects":
        monkeypatch.setattr(object_routes, "get_terrain_connection", lambda _dbname: connection)
        monkeypatch.setattr(object_routes, "_get_next_object_id", lambda _conn: 6)
        monkeypatch.setattr(object_routes, "_get_object_types", lambda _conn: ["wall"])
        monkeypatch.setattr(object_routes, "q_list_objects_with_sjs", lambda _conn: [] if empty else [(5, "wall", None, "", sus)])
    else:
        monkeypatch.setattr(section_routes, "get_terrain_connection", lambda _dbname: connection)
        monkeypatch.setattr(section_routes, "get_sections_list_sql", lambda: "sections-list")
        monkeypatch.setattr(section_routes, "list_authors_sql", lambda: "authors-list")
        monkeypatch.setattr(section_routes, "list_sj_ids_sql", lambda: "sj-list")
    with client.session_transaction() as session:
        session["selected_db"] = "01_ListTest"
    return connection


class _ListMarkup(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.template = None
        self.links = {None: []}
        self.columns = []
        self.search_values = []
        self.buttons = {}
        self.button_text = {}
        self.current_button = None
        self.section_payload = None
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
        elif tag == "td" and "data-search-value" in attrs:
            self.search_values.append(attrs["data-search-value"])
        elif tag == "button":
            if "data-items-template" in attrs:
                self.current_button = attrs["data-items-template"]
                self.buttons[self.current_button] = attrs
                self.button_text[self.current_button] = ""
            if "data-section" in attrs:
                self.section_payload = json.loads(attrs["data-section"])

    def handle_data(self, data):
        if self.current_button:
            self.button_text[self.current_button] += data

    def handle_endtag(self, tag):
        if tag == "template":
            self.template = None
        elif tag == "button":
            self.current_button = None


@pytest.mark.parametrize("kind", ["objects", "sections"])
@pytest.mark.parametrize("count", [0, 3, 4, 10, 11, 15])
def test_entity_listing_controls_limits_and_complete_links(client, monkeypatch, kind, count):
    sus = list(range(1, count + 1))
    docs = {media: [f'{media}_{index}.jpg' for index in range(1, count + 1)]
            for media in ("photos", "photograms", "drawings", "sketches")}
    connection = _prepare(client, monkeypatch, kind, sus, docs)
    response = client.get(f"/{kind}")
    assert response.status_code == 200
    assert connection.closed
    html = response.get_data(as_text=True)
    parsed = _ListMarkup(html)
    expected_columns = ["id", "type", "superior", "sus"] if kind == "objects" else [
        "id", "type", "description", "srid", "ranges", "sus", "documentation",
    ]
    assert parsed.columns == expected_columns
    assert html.count("data-column-search\n") == len(expected_columns)
    assert html.count("data-column-sort\n") == len(expected_columns)
    assert f'id="{kind}NoMatches" hidden' in html
    assert f'id="{kind}ResetTable"' in html
    assert f'id="{kind}PaginationSummary"' in html
    assert 'js/list_table.js' in html
    assert ", ".join(str(sj_id) for sj_id in sus) in parsed.search_values
    with client.application.test_request_context():
        urls = [url_for("su.add_su", edit_su=sj_id) for sj_id in sus]
        assert all(url in parsed.links[None] for url in urls[:10])
        assert all(url not in parsed.links[None] for url in urls[10:])
        template_id = f"{kind}-items-5-sus"
        if count > 10:
            assert parsed.links[template_id] == urls
            assert parsed.button_text[template_id] == f"+{count - 10}"
            assert parsed.buttons[template_id]["data-bs-target"] == f"#{kind}ItemsModal"
        else:
            assert template_id not in parsed.buttons
        if kind == "sections":
            assert parsed.section_payload["sj_ids"] == sus
            for media, endpoint, parameter in (
                ("photos", "photos.serve_photo_file", "id_photo"),
                ("photograms", "photograms.serve_photogram_file", "id_photogram"),
                ("drawings", "drawings.serve_drawing", "id_drawing"),
                ("sketches", "sketches.serve_sketch_file", "id_sketch"),
            ):
                urls = [url_for(endpoint, **{parameter: value}) for value in docs[media]]
                assert all(url in parsed.links[None] for url in urls[:3])
                assert all(url not in parsed.links[None] for url in urls[3:])
                template_id = f"sections-items-5-{media}"
                if count > 3:
                    assert parsed.links[template_id] == urls
                    assert parsed.button_text[template_id] == f"+{count - 3}"
                    assert parsed.buttons[template_id]["data-bs-target"] == "#sectionsItemsModal"
                else:
                    assert template_id not in parsed.buttons


@pytest.mark.parametrize("kind", ["objects", "sections"])
def test_empty_entity_listing_has_no_table_controls(client, monkeypatch, kind):
    _prepare(client, monkeypatch, kind, [], {}, empty=True)
    response = client.get(f"/{kind}")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert f'id="{kind}Table"' not in html
    assert "No objects were found." in html if kind == "objects" else "No sections stored yet." in html
