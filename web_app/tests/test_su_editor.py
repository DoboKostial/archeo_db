from datetime import date
from html.parser import HTMLParser

import pytest
from flask import render_template_string

from app.routes import su as su_routes


class _Connection:
    def __init__(self, typ="deposit", missing=False):
        self.closed = False
        self.queries = []
        self.query = ""
        self.row = [None] * 32
        self.row[:10] = [7, typ, "Description", "Interpretation", date(2026, 10, 6),
                         "author@example.invalid", True, False, 0, 3]
        self.row[10:16] = ["fill", "brown", "clear", "sand", "loose", "pick"]
        self.row[16:21] = ["pit", True, "round", "straight", "flat"]
        self.row[21:28] = ["wall", "masonry", "mortar", "stone", 0, 1.2, 3.4]
        self.row[28:] = [["P1"], [1], [8], [9]]
        if missing:
            self.row = None

    def cursor(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, query, params=None):
        self.query = query
        self.queries.append((query, params))

    def fetchone(self):
        return tuple(self.row) if self.row else None

    def fetchall(self):
        if self.query == su_routes.list_authors_sql():
            return [("author@example.invalid",)]
        if self.query == su_routes.list_polygon_names_sql():
            return [("P1",), ("P2",)]
        raise AssertionError("Unexpected editor query")

    def close(self):
        self.closed = True


@pytest.mark.parametrize("typ", ["deposit", "negativ", "structure"])
def test_shared_editor_api_returns_complete_form_data(client, monkeypatch, typ):
    connection = _Connection(typ)
    monkeypatch.setattr(su_routes, "get_terrain_connection", lambda db: connection)
    with client.session_transaction() as session:
        session["selected_db"] = "01_EditorTest"
    response = client.get("/su/api/7")
    data = response.get_json()
    assert response.status_code == 200
    assert connection.closed
    assert connection.queries[0][1] == (7,)
    assert data["authors"] == ["author@example.invalid"]
    assert data["polygons"] == ["P1", "P2"]
    assert data["editor"] == su_routes._harris_su_payload(tuple(connection.row))["editor"]
    assert data["editor"]["typ"] == typ
    assert data["editor"]["excav_extent"] == 0
    assert data["editor"]["length_m"] == 0
    assert data["editor"]["polygon_names"] == ["P1"]


def test_shared_editor_missing_su_does_not_load_option_lists(client, monkeypatch):
    connection = _Connection(missing=True)
    monkeypatch.setattr(su_routes, "get_terrain_connection", lambda db: connection)
    with client.session_transaction() as session:
        session["selected_db"] = "01_EditorTest"
    response = client.get("/su/api/7")
    assert response.status_code == 404
    assert "editor" not in response.get_json()
    assert len(connection.queries) == 1
    assert connection.closed


@pytest.mark.parametrize("logged_in", [True, False])
def test_shared_editor_guards_precede_db_connection(client, monkeypatch, logged_in):
    def unexpected(db):
        pytest.fail("The guard must run before opening the database")

    monkeypatch.setattr(su_routes, "get_terrain_connection", unexpected)
    if not logged_in:
        client.delete_cookie("token")
        with client.session_transaction() as session:
            session["selected_db"] = "01_EditorTest"
    response = client.get("/su/api/7")
    assert response.status_code == 302


class _Markup(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.ids = []
        self.inputs = {}
        self.links = []
        self.feed(html)

    def handle_starttag(self, tag, attributes):
        attrs = dict(attributes)
        if "id" in attrs:
            self.ids.append(attrs["id"])
        if tag == "input" and "name" in attrs:
            self.inputs[attrs["name"]] = attrs.get("value")
        if tag == "a":
            self.links.append(attrs)


@pytest.mark.parametrize("path, endpoint", [
    ("/add-sj", "su.add_su"), ("/polygons", "polygons.polygons"),
    ("/objects", "archeo_objects.objects"), ("/sections", "sections.sections"),
    ("/harrismatrix", "su.harrismatrix"), ("/photos", "photos.photos"),
    ("/sketches", "sketches.sketches"), ("/drawings", "drawings.drawings"),
    ("/photograms", "photograms.photograms"),
])
def test_one_global_editor_retains_origin_and_has_interactive_su_links(app, path, endpoint):
    with app.test_request_context(path + "?page=2&q=wall"):
        html = render_template_string(
            """{% extends "base.html" %}
            {% from "macros/list_table.html" import su_links %}
            {% from "_media_entity_links.html" import entity_link %}
            {% block content %}
              {{ su_links(range(1, 13)|list, 1, "test", "Test") }}
              {{ entity_link("su", 42) }}
            {% endblock %}""",
            selected_db="01_EditorTest", authors=["author@example.invalid"], polygons=["P1"],
        )
    markup = _Markup(html)
    assert markup.ids.count("editSuModal") == 1
    assert html.index('id="editSuModal"') > html.index("</main>")
    assert html.count("js/su_edit.js") == 1
    assert markup.inputs["return_to"] == endpoint
    assert markup.inputs["return_query"] == "page=2&q=wall"
    assert all(link.get("data-su-id") for link in markup.links)
    assert len(markup.links) == 23
    assert "float-none w-auto px-2" in html


def test_su_edit_preserves_source_query_and_drops_auto_open_parameter(client):
    with client.session_transaction() as session:
        session["selected_db"] = "01_EditorTest"
    response = client.post("/su/edit", data={
        "id_sj": "invalid", "return_to": "photos.photos",
        "return_query": "page=2&q=wall+%26+floor&edit_su=7",
    })
    assert response.status_code == 302
    assert response.headers["Location"] == "/photos?page=2&q=wall+%26+floor"


def test_su_edit_reencodes_untrusted_query_as_query_data(client):
    with client.session_transaction() as session:
        session["selected_db"] = "01_EditorTest"
    response = client.post("/su/edit", data={
        "id_sj": "invalid", "return_to": "//example.invalid/",
        "return_query": "q=%0D%0ALocation%3A+https%3A%2F%2Fexample.invalid",
    })
    assert response.status_code == 302
    assert response.headers["Location"].startswith("/add-sj?q=%0D%0A")
