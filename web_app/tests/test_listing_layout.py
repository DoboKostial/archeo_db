from html.parser import HTMLParser
import os
import shutil
import subprocess
import threading

import pytest
from flask import Flask, g, render_template, url_for
from werkzeug.serving import make_server

from app.routes.su import _su_row_to_dict


class _Markup(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.ids = []
        self.tables = []
        self.feed(html)

    def handle_starttag(self, tag, attributes):
        attrs = dict(attributes)
        if "id" in attrs:
            self.ids.append(attrs["id"])
        if tag == "table":
            self.tables.append(set(attrs.get("class", "").split()))


def _context(count=0):
    sus = []
    polygons = []
    sections = []
    docs = {kind: [] for kind in ("photos", "photograms", "drawings", "sketches")}
    for index in range(1, count + 1):
        row = [None] * 32
        row[:9] = [index, "deposit", "Layer", "Floor", None, "author@example.invalid", True, False, "100"]
        row[27:32] = [[], [], [], [], docs]
        su = _su_row_to_dict(row)
        su["polygon_memberships"] = []
        sus.append(su)
        polygons.append({
            "id": index, "name": f"Trench {index}", "parent": None,
            "allocation_reason": "research_phase", "has_top": True, "has_bottom": False,
            "points": 4, "notes": "", "top_ranges": [], "bottom_ranges": [],
            "sj_ids": [index], "documented_by": docs,
        })
        sections.append({
            "id": index, "type": "standard", "description": "Face", "srid": "5514",
            "ranges": "1-4", "ranges_edit": [{"from": 1, "to": 4}],
            "sj_ids": [index], "documented_by": docs,
        })
    return {
        "selected_db": "01_LayoutTest", "suggested_id": count + 1, "today_iso": "2026-10-05",
        "sus": sus, "su_for_media": sus, "polygons": polygons, "sections": sections,
        "sj_ids": list(range(1, count + 1)), "authors": [], "form_data": {},
        "sj_count_total": count, "sj_count_deposit": count, "sj_count_negativ": 0, "sj_count_structure": 0,
        "open_edit_su_id": None, "open_edit_section_id": None, "open_edit_polygon_name": None,
        "open_edit_find_id": None, "open_edit_sample_id": None,
        "objects": [], "object_types": [], "find_types": [], "sample_types": [],
        "last_finds": [], "last_samples": [], "allowed_ext": ".jpg",
        "photos": [], "photograms": [], "sketches": [], "drawings": [],
        "photo_typ_choices": [], "photogram_typ_choices": [], "sketch_typ_choices": [],
        "stats": {"total_cnt": 0, "total_bytes_h": "0 B", "orphan_cnt": 0, "by_type": []},
        "filters": {}, "page": 1, "per_page": 10, "prev_url": None, "next_url": None,
        "filtered_cnt": 0, "has_next": False, "users": [], "user_roles": [],
        "terrain_dbs": [], "total_pages": 1,
        "overview": {"point_count": 0, "last_point_id": None}, "target_srid": 5514, "codes": [],
    }


@pytest.mark.parametrize("count", [0, 25])
@pytest.mark.parametrize("template, endpoint, selector, heading, modal_prefix, media", [
    ("polygons", "polygons.new_polygon_manual", "polyDocSelect", "Existing polygons", "modalPoly",
     ("Photos", "Sketches", "Photograms")),
    ("add_su", "su.add_su", "suMediaInput", "Existing SUs", "modal",
     ("Photos", "Sketches", "Photograms", "Drawings")),
    ("sections", "sections.new_section_manual", "secDocSelect", "Existing sections", "modalSec",
     ("Photos", "Sketches", "Photograms", "Drawings")),
])
def test_documentation_follows_form_before_listing(app, count, template, endpoint, selector, heading, modal_prefix, media):
    with app.test_request_context():
        html = render_template(f"{template}.html", **_context(count))
        form = f'action="{url_for(endpoint)}"'
    assert html.index(form) < html.index("Attach graphic documentation") < html.index(heading)
    parsed = _Markup(html)
    assert len(parsed.ids) == len(set(parsed.ids))
    assert parsed.ids.count(selector) == 1
    for kind in media:
        assert f'data-bs-target="#{modal_prefix}{kind}"' in html
        assert parsed.ids.count(f"{modal_prefix}{kind}") == 1
    assert "SUs list" not in html
    assert "Stored SUs" not in html
    assert all("table-striped" in classes for classes in parsed.tables)


@pytest.mark.parametrize("template, headings", [
    ("objects", ["Existing objects"]),
    ("list_objects", ["Existing archaeological objects"]),
    ("finds_samples", ["Existing finds", "Existing samples"]),
    ("geodesy", ["Existing points"]),
    ("admin", ["Existing users", "Existing terrain databases"]),
    ("photos", ["Existing photos"]),
    ("photograms", ["Existing photograms"]),
    ("sketches", ["Existing sketches"]),
    ("drawings", ["Existing drawings"]),
])
def test_inventory_names_and_striped_tables(app, template, headings):
    with app.test_request_context():
        html = render_template(f"{template}.html", **_context())
    assert all(heading in html for heading in headings)
    parsed = _Markup(html)
    assert all("table-striped" in classes for classes in parsed.tables)


def test_shared_assets_use_updated_cache_version(app):
    with app.test_request_context():
        for template in ("polygons", "add_su", "objects", "sections"):
            html = render_template(f"{template}.html", **_context(1))
            assert "css/custom.css?v=list-layout-2" in html
            assert "js/list_table.js?v=list-layout-2" in html


UPLOAD_AUTHOR_MODALS = [
    ("add_su", ["modalPhotos", "modalSketches", "modalDrawings"]),
    ("polygons", ["modalPolyPhotos", "modalPolySketches"]),
    ("sections", ["modalSecPhotos", "modalSecSketches", "modalSecDrawings"]),
    ("finds_samples", ["modalFindPhotos", "modalFindSketches", "modalSamplePhotos", "modalSampleSketches"]),
]


class _ModalInputs(HTMLParser):
    def __init__(self, html, input_name):
        super().__init__()
        self.input_name = input_name
        self.depth = 0
        self.modal = None
        self.modal_depth = None
        self.inputs = {}
        self.feed(html)

    def handle_starttag(self, tag, attributes):
        attrs = dict(attributes)
        if tag == "div":
            self.depth += 1
            if "modal" in attrs.get("class", "").split():
                self.modal = attrs.get("id")
                self.modal_depth = self.depth
        if tag == "input" and attrs.get("name") == self.input_name and self.modal:
            self.inputs.setdefault(self.modal, []).append(attrs)

    def handle_endtag(self, tag):
        if tag == "div":
            if self.depth == self.modal_depth:
                self.modal = self.modal_depth = None
            self.depth -= 1


@pytest.mark.parametrize("email", ["logged-in@example.invalid", "", 'quoted"author@example.invalid'])
@pytest.mark.parametrize("template, modals", UPLOAD_AUTHOR_MODALS)
def test_upload_modal_authors_default_to_logged_in_user_and_remain_editable(app, template, modals, email):
    with app.test_request_context():
        g.user_email = email
        html = render_template(f"{template}.html", **_context())
    parsed = _ModalInputs(html, "author")
    assert set(parsed.inputs) == set(modals)
    for inputs in parsed.inputs.values():
        assert len(inputs) == 1
        author = inputs[0]
        assert author["value"] == email
        assert "data-default-author" in author
        assert author["type"] == "email"
        assert "readonly" not in author and "disabled" not in author


@pytest.mark.parametrize('template, modal', [
    ('sections', 'modalSecPhotograms'), ('add_su', 'modalPhotograms'),
])
def test_photogram_attachment_modal_has_required_editable_date(app, template, modal):
    with app.test_request_context():
        html = render_template(f'{template}.html', **_context())
    fields = _ModalInputs(html, 'datum').inputs[modal]
    assert len(fields) == 1
    assert fields[0]['type'] == 'date'
    assert fields[0]['value'] == _context()['today_iso']
    assert 'required' in fields[0]
    assert 'readonly' not in fields[0] and 'disabled' not in fields[0]


@pytest.mark.skipif(os.environ.get("ARCHEODB_TEST_BROWSER") != "1" or not shutil.which("chromium"),
                    reason="Set ARCHEODB_TEST_BROWSER=1 and install Chromium")
@pytest.mark.parametrize("template, modals", UPLOAD_AUTHOR_MODALS)
def test_opening_upload_modals_restores_empty_authors_but_preserves_manual_choices(app, tmp_path, template, modals):
    context = _context(1)
    if template == "add_su":
        context["polygons"] = ["Trench 1"]
    with app.test_request_context():
        g.user_email = "logged-in@example.invalid"
        html = render_template(f"{template}.html", **context)
    setup = """<script>
      window.modalPreviewErrors = [];
      window.addEventListener('error', event => modalPreviewErrors.push(event.message));
      window.addEventListener('unhandledrejection', event => modalPreviewErrors.push(String(event.reason)));
      window.fetch = async () => ({ok:true,json:async () => ({ok:true,rows:[],total:0})});
      </script>"""
    html = html.replace("</head>", setup + "</head>")
    checks = """<pre id="uploadAuthorResult">RUNNING</pre><script>
      document.addEventListener('DOMContentLoaded', async () => {
        const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
        const check = (value, message) => {if (!value) throw Error(message);};
        try {
          for (const [id,value] of [['suMediaInput','1'],['polyDocSelect','Trench 1'],['secDocSelect','1']]) {
            const selector = document.getElementById(id);
            if (selector) {selector.value = value;selector.dispatchEvent(new Event('change'));}
          }
          const fields = [...document.querySelectorAll('.modal input[data-default-author]')];
          check(fields.length === EXPECTED_COUNT, 'Missing modal author defaults');
          for (const input of fields) {
            const modal = input.closest('.modal');
            const instance = bootstrap.Modal.getOrCreateInstance(modal);
            check(input.value === 'logged-in@example.invalid', 'Initial logged-in author missing');
            input.value = '';
            instance.show(); await sleep(500);
            check(modal.classList.contains('show'), 'Upload modal did not open');
            check(input.value === 'logged-in@example.invalid', 'Empty author not restored on open');
            check(new FormData(input.form).get('author') === 'logged-in@example.invalid', 'Default author not submitted');
            input.value = 'other@example.invalid';
            instance.hide(); await sleep(500);
            instance.show(); await sleep(500);
            check(input.value === 'other@example.invalid', 'Manual author overwritten on reopen');
            check(new FormData(input.form).get('author') === 'other@example.invalid', 'Manual author not submitted');
            input.form.reset();
            check(input.value === 'logged-in@example.invalid', 'Reset did not restore default author');
            input.value = '   ';
            instance.hide(); await sleep(500);
            instance.show(); await sleep(500);
            check(input.value === 'logged-in@example.invalid', 'Whitespace author not restored');
            instance.hide(); await sleep(500);
          }
          const photogramModal = document.getElementById('modalSecPhotograms') ||
            document.getElementById('modalPhotograms') || document.getElementById('modalPolyPhotograms');
          if (photogramModal) {
            const date = photogramModal.querySelector('input[name="datum"]');
            check(date && date.required, 'Photogram attachment date missing or optional');
            check(date.value === '2026-10-05', 'Photogram date was not prefilled');
            const instance = bootstrap.Modal.getOrCreateInstance(photogramModal);
            instance.show(); await sleep(500);
            photogramModal.querySelector('input[name="photogram_typ"]').value = 'other';
            date.value = '';
            check(!date.form.checkValidity(), 'Empty photogram date accepted by the form');
            date.value = '2024-07-19';
            check(date.form.checkValidity(), 'Valid photogram date rejected');
            check(new FormData(date.form).get('datum') === '2024-07-19', 'Selected photogram date not submitted');
            instance.hide(); await sleep(500);
          }
          const edit = document.getElementById('editSuModal');
          const author = document.getElementById('edit_author');
          author.add(new Option('original@example.invalid','original@example.invalid'));
          author.value = 'original@example.invalid';
          edit.dispatchEvent(new Event('show.bs.modal',{bubbles:true}));
          check(author.value === 'original@example.invalid', 'Stored edit author was replaced');
          author.value = '';
          edit.dispatchEvent(new Event('show.bs.modal',{bubbles:true}));
          check(author.value === '', 'Unknown edit author was defaulted');
          check(!modalPreviewErrors.length, modalPreviewErrors.join('; '));
          document.getElementById('uploadAuthorResult').dataset.status = 'passed';
          document.getElementById('uploadAuthorResult').textContent = 'PASS';
        } catch(error) {
          document.getElementById('uploadAuthorResult').textContent = 'FAIL: ' + error.message;
        }
      });
      </script>""".replace("EXPECTED_COUNT", str(len(modals)))
    html = html.replace("</body>", checks + "</body>")
    preview = Flask("modal-author-preview", static_folder=app.static_folder)
    preview.add_url_rule("/", view_func=lambda: html)
    server = make_server("127.0.0.1", 0, preview, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        result = subprocess.run([
            "chromium", "--headless", "--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage",
            "--no-first-run", "--no-default-browser-check", f"--user-data-dir={tmp_path / 'profile'}",
            "--virtual-time-budget=20000", "--dump-dom", f"http://127.0.0.1:{server.server_port}/",
        ], capture_output=True, text=True, timeout=40)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
    assert result.returncode == 0, result.stderr[-2000:]
    assert '<pre id="uploadAuthorResult" data-status="passed">PASS</pre>' in result.stdout, result.stdout[-6000:]
