from html.parser import HTMLParser
import os
from pathlib import Path
import shutil

import pytest
from flask import render_template, url_for

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
    assert 'id="edit-ranges-container"' not in html
    assert 'id="geometryModal"' in html
    assert 'data-geometry-kind="section"' in html
    assert 'id="editSectionSjs"' in html
    assert 'id="sectionSjs"' in html
    assert html.count('name="point_from"') == 1
    assert html.count('name="point_to"') == 1
    assert 'id="sectionPointFrom"' in html
    assert 'id="sectionPointTo"' in html
    assert 'id="replaceSectionGeometry"' in html
    assert 'Section line points (optional)' in html
    assert 'Point ranges are mandatory' not in html
    assert html.count("data-su-enhanced hidden") == 2
    assert html.count('data-su-selected aria-label="Selected SUs"') == 2
    assert "Hold Shift/Ctrl" not in html
    assert "js/section_su_picker.js?v=section-su-picker-1" in html
    assert 'data-column="srid"' not in html
    assert 'colspan="8"' in html
    assert "Show all on map" in html
    assert '/spatial/map?kind=section' in html
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
        search = next(attrs for attrs in parsed.inputs if attrs["id"] == f"{select_id}Search")
        assert search["role"] == "combobox"
        assert search["aria-autocomplete"] == "list"
        assert search["aria-controls"] == f"{select_id}Suggestions"
        assert ("disabled" in search) == (not sj_ids)


@pytest.mark.skipif(os.environ.get("ARCHEODB_TEST_BROWSER") != "1" or not shutil.which("firefox"),
                    reason="Set ARCHEODB_TEST_BROWSER=1 and install Firefox")
def test_searchable_section_su_selection_and_modal_prefill_in_browser(app, tmp_path):
    from test_listing_layout import _context, _Markup
    from test_spatial_browser import _firefox_result

    context = _context(2)
    context["sj_ids"] = list(range(1, 112))
    context["sections"][0]["sj_ids"] = [10, 12]
    assets = {}
    static = Path(app.static_folder)
    with app.test_request_context("/sections"):
        html = render_template("sections.html", **context)
        for tag, attrs in _Markup(html).elements:
            src = attrs.get("src", "")
            if tag == "script" and src.startswith(url_for("static", filename="js/")):
                name = src.split("?")[0].rsplit("/", 1)[-1]
                uri = (static / "js" / name).as_uri()
                html = html.replace(src, uri)
                assets[name] = uri
    html = "\n".join(line for line in html.splitlines() if "<link " not in line and "unpkg.com" not in line)
    styles = (static / "css/bootstrap.min.css").read_text() + (static / "css/custom.css").read_text()
    setup = """<script>
      window.previewErrors=[];
      addEventListener('error', event => previewErrors.push(event.message));
      addEventListener('unhandledrejection', event => previewErrors.push(String(event.reason)));
      window.fetch=async () => ({ok:true,json:async () => ({rows:[],total:0})});
    </script>"""
    html = html.replace("</head>", "<style>" + styles + "</style>" + setup + "</head>")
    checks = '''<pre id="result">RUNNING</pre><script>
      document.addEventListener('DOMContentLoaded', async () => {
        const sleep=ms => new Promise(resolve => setTimeout(resolve,ms));
        const check=(value,message) => {if(!value) throw Error(message);};
        const values=select => new FormData(select.form).getAll('ref_sj[]').join(',');
        const type=(input,text) => {input.value=text; input.dispatchEvent(new Event('input'));};
        const key=(input,value) => input.dispatchEvent(new KeyboardEvent('keydown',{key:value,bubbles:true,cancelable:true}));
        try {
          const select=document.getElementById('sectionSjs');
          const picker=select.closest('[data-cut-su-picker]');
          const input=picker.querySelector('[data-su-search]');
          const suggestions=picker.querySelector('[data-su-suggestions]');
          const chips=picker.querySelector('[data-su-selected]');
          check(select.hidden && getComputedStyle(select).display==='none' &&
            !picker.querySelector('[data-su-enhanced]').hidden, 'Native select was not replaced');
          check(values(select)==='', 'Initial selection should be empty');
          input.focus(); type(input,'1');
          check(suggestions.children.length===20, 'Suggestions not limited to 20');
          check(picker.querySelector('[data-su-matches]').textContent.includes('20'), 'Truncation not shown');
          type(input,'12');
          check(suggestions.children[0].textContent==='SU 12', 'Exact match must be first');
          // Exercise the real pointer sequence used for both mouse and touch selections.
          suggestions.children[0].dispatchEvent(new PointerEvent('pointerdown',{bubbles:true,cancelable:true}));
          suggestions.children[0].click();
          check(values(select)==='12' && chips.children.length===1, 'Click did not add SU');
          check(input.value==='' && suggestions.hidden, 'Search did not clear after adding');
          type(input,'12');
          check(suggestions.hidden && chips.children.length===1, 'Duplicate selection offered');
          type(input,'10'); key(input,'ArrowDown');
          check(input.getAttribute('aria-activedescendant')===suggestions.children[0].id, 'Keyboard focus not exposed');
          key(input,'Enter');
          check(values(select)==='10,12', 'Keyboard selection replaced existing SUs');
          type(input,'no-such-su'); key(input,'Enter');
          check(values(select)==='10,12' && suggestions.hidden, 'Invalid SU added');
          check(picker.querySelector('[data-su-matches]').textContent.includes('No matching'), 'No-match status missing');
          type(input,'1'); key(input,'ArrowUp'); key(input,'Enter');
          check(select.selectedOptions.length===3, 'ArrowUp selection failed');
          picker.querySelector('[aria-label="Remove SU 12"]').click();
          check(!values(select).split(',').includes('12') && chips.children.length===2, 'Removal failed');
          type(input,'12'); suggestions.children[0].click();
          check(select.selectedOptions.length===3, 'Removed SU could not be re-added');
          type(input,'2'); key(input,'Escape');
          check(input.value==='' && suggestions.hidden && select.selectedOptions.length===3, 'Escape changed selection');
          input.form.reset(); await sleep(30);
          check(values(select)==='' && !chips.children.length, 'Form reset retained selected SUs');

          const modal=document.getElementById('editSectionModal');
          const edit=document.getElementById('editSectionSjs');
          const editPicker=edit.closest('[data-cut-su-picker]');
          const editInput=editPicker.querySelector('[data-su-search]');
          const instance=bootstrap.Modal.getOrCreateInstance(modal);
          const buttons=[...document.querySelectorAll('[data-section]')];
          const show=button => new Promise(resolve => {
            modal.addEventListener('shown.bs.modal',resolve,{once:true}); instance.show(button);
          });
          const hide=() => new Promise(resolve => {
            modal.addEventListener('hidden.bs.modal',resolve,{once:true}); instance.hide();
          });
          await show(buttons[0]);
          check(values(edit)==='10,12' && editPicker.querySelector('[data-su-selected]').children.length===2, 'Saved SUs not prefilled');
          type(editInput,'11'); key(editInput,'Enter');
          check(values(edit)==='10,11,12', 'Modal selection failed');
          check(values(select)==='', 'Modal changed the create form');
          editPicker.querySelector('[aria-label="Remove SU 10"]').click();
          check(values(edit)==='11,12', 'Modal removal failed');
          for(const button of [...editPicker.querySelectorAll('[data-su-selected] button')]) button.click();
          check(values(edit)==='' && !editPicker.querySelector('[data-su-selected]').children.length, 'Cannot remove all SUs');
          type(editInput,'1');
          await hide();
          await show(buttons[1]);
          check(values(edit)==='2' && editInput.value==='', 'Previous modal selection leaked: '+values(edit)+' / '+editInput.value);
          await hide();
          await show(buttons[0]);
          check(values(edit)==='10,12', 'Cancelled edits changed saved prefill');
          check(!previewErrors.length, previewErrors.join('; '));
          document.getElementById('result').textContent='PASS';
        } catch(error) {document.getElementById('result').textContent='FAIL: '+error.message;}
      });
    </script>'''
    html = html.replace("</body>", checks + "</body>")
    assert _firefox_result(html, assets, tmp_path) == "PASS"
