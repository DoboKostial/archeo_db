from html.parser import HTMLParser
import json
import os
from pathlib import Path
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
        self.elements = []
        self.feed(html)

    def handle_starttag(self, tag, attributes):
        attrs = dict(attributes)
        self.elements.append((tag, attrs))
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


def test_navigation_has_viewport_and_accessible_collapse_toggle(app):
    with app.test_request_context():
        html = render_template("base.html", user_email="user@example.invalid", user_role="archeolog")
    elements = _Markup(html).elements
    viewport = next(attrs for tag, attrs in elements if tag == "meta" and attrs.get("name") == "viewport")
    assert viewport["content"] == "width=device-width, initial-scale=1"
    toggle = next(attrs for tag, attrs in elements if tag == "button" and "navbar-toggler" in attrs.get("class", ""))
    assert toggle["data-bs-toggle"] == "collapse"
    assert toggle["data-bs-target"] == "#mainNavigation"
    assert toggle["aria-controls"] == "mainNavigation"
    assert toggle["aria-expanded"] == "false"
    assert toggle["aria-label"]
    assert _Markup(html).ids.count("mainNavigation") == 1
    for endpoint in ("su.add_su", "polygons.polygons", "sections.sections", "reports.reports"):
        with app.test_request_context():
            assert f'href="{url_for(endpoint)}"' in html


@pytest.mark.parametrize("color", ["", "brown", "10YR 4/3", 'grey with <white> & "black" flecks'])
def test_deposit_color_can_be_typed_or_selected_and_preserves_form_data(app, color):
    context = _context()
    context["form_data"] = {"color": color}
    with app.test_request_context("/add-sj"):
        html = render_template("add_su.html", **context)
    elements = _Markup(html).elements
    color_input = next(attrs for tag, attrs in elements if tag == "input" and attrs.get("id") == "deposit_color")
    assert color_input["type"] == "text"
    assert color_input["name"] == "color"
    assert color_input["value"] == color
    assert "readonly" not in color_input and "disabled" not in color_input
    assert any(tag == "label" and attrs.get("for") == "deposit_color" for tag, attrs in elements)
    assert any(tag == "button" and attrs.get("data-choice-value") == "brown" for tag, attrs in elements)
    edit_input = next(attrs for tag, attrs in elements if tag == "input" and attrs.get("id") == "edit_color")
    assert edit_input["type"] == "text" and edit_input["name"] == "color"


@pytest.mark.skipif(os.environ.get("ARCHEODB_TEST_BROWSER") != "1" or not shutil.which("firefox"),
                    reason="Set ARCHEODB_TEST_BROWSER=1 and install Firefox")
def test_tablet_navigation_and_deposit_color_in_browser(app, tmp_path):
    from test_spatial_browser import _firefox_result

    context = _context()
    context.update(user_email="user@example.invalid", user_name="Test User", user_role="archeolog")
    assets = {}
    static = Path(app.static_folder)
    with app.test_request_context("/add-sj"):
        html = render_template("add_su.html", **context)
        for name in ("bootstrap.bundle.min.js", "su_edit.js", "su.js", "list_table.js", "spatial.js"):
            # Match cache-busted URLs as rendered, while keeping all browser traffic local.
            for tag, attrs in _Markup(html).elements:
                src = attrs.get("src", "")
                if tag == "script" and src.split("?")[0] == url_for("static", filename="js/" + name):
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
    # Each same-origin iframe has a real layout viewport of the requested width.
    outer = '''<!doctype html><pre id="result">RUNNING</pre><script>
      const page = PAGE;
      const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
      const check = (value, message) => {if (!value) throw Error(message);};
      (async () => {
        try {
          for (const width of [375,768,820,1024,1280,1920]) {
            const frame=document.createElement('iframe');
            frame.style.cssText=`width:${width}px;height:1100px;border:0`;
            const loaded=new Promise(resolve => frame.onload=resolve);
            frame.srcdoc=page; document.body.append(frame); await loaded;
            const win=frame.contentWindow, doc=frame.contentDocument;
            const nav=doc.querySelector('.app-navbar');
            const menu=doc.getElementById('mainNavigation');
            const toggle=doc.querySelector('.navbar-toggler');
            const narrow=width<1200;
            check((win.getComputedStyle(toggle).display!=='none')===narrow, 'Wrong navigation breakpoint '+width);
            if(narrow) {
              check(win.getComputedStyle(menu).display==='none', 'Menu should initially collapse '+width);
              toggle.click(); await sleep(400);
              check(toggle.getAttribute('aria-expanded')==='true', 'Toggle failed '+width);
            }
            for (const link of menu.querySelectorAll('.navbar-nav > li > a')) {
              const bounds=link.getBoundingClientRect();
              check(bounds.width>0 && bounds.height>0 && bounds.left>=0 && bounds.right<=width+1,
                'Navigation link hidden or clipped '+width+' '+link.textContent);
            }
            check(nav.scrollWidth<=width+1, 'Navbar overflows '+width);
            doc.getElementById('navMediaDropdown').click(); await sleep(50);
            for(const link of menu.querySelectorAll('.dropdown-item')) {
              const bounds=link.getBoundingClientRect();
              check(bounds.width>0 && bounds.left>=0 && bounds.right<=width+1, 'Media link clipped '+width);
            }
            doc.getElementById('navMediaDropdown').click();
            const type=doc.getElementById('sj_typ'); type.value='deposit';
            type.dispatchEvent(new win.Event('change'));
            const input=doc.getElementById('deposit_color');
            const picker=input.closest('.deposit-color-picker');
            const choose=picker.querySelector('[data-color-toggle]');
            check(input.getBoundingClientRect().width>60, 'Color input not usable '+width);
            choose.click(); picker.querySelector('[data-choice-value="brown"]').click();
            check(input.value==='brown', 'Swatch did not set text '+width);
            check(new win.FormData(input.form).get('color')==='brown', 'Swatch not submitted '+width);
            input.value='10YR 4/3'; input.dispatchEvent(new win.Event('input'));
            check(!picker.querySelector('.active'), 'Stale swatch after typing '+width);
            check(new win.FormData(input.form).get('color')==='10YR 4/3', 'Manual color not submitted '+width);
            input.value=''; input.dispatchEvent(new win.Event('input'));
            choose.click(); picker.querySelector('[data-choice-value="ochre"]').click();
            check(input.value==='ochre', 'Palette failed after clearing '+width);
            input.form.reset(); await sleep(20);
            check(input.value==='' && !picker.querySelector('.active'), 'Reset did not clear color '+width);
            const fillIds=doc.getElementById('new_fill_ids');
            const negativeIds=doc.getElementById('new_negative_ids');
            for(const typ of ['deposit','structure','negativ']) {
              type.value=typ; type.dispatchEvent(new win.Event('change'));
              const isNegative=typ==='negativ';
              check(fillIds.disabled===!isNegative && negativeIds.disabled===isNegative, 'Wrong fill direction '+typ);
              const field=isNegative?fillIds:negativeIds;
              field.value='100, 200';
              const formData=new win.FormData(field.form);
              check(formData.get(field.name)==='100, 200' && !formData.has(isNegative?'negative_ids':'fill_ids'),
                'Hidden fill fields submitted '+typ);
              check(field.getBoundingClientRect().width>60, 'Fill field not visible '+width);
            }
            if(width===768) {
              const modal=doc.getElementById('editSuModal');
              const instance=win.bootstrap.Modal.getOrCreateInstance(modal);
              for(const typ of ['negativ','deposit','structure']) {
                const button=doc.createElement('button');
                button.dataset.su=JSON.stringify({id:10,typ,fill_ids:typ==='negativ'?[201,202]:[],negative_ids:typ==='negativ'?[]:[100,200]});
                const shown=new Promise(resolve => modal.addEventListener('shown.bs.modal',resolve,{once:true}));
                instance.show(button); await shown;
                const field=doc.getElementById(typ==='negativ'?'edit_fill_ids':'edit_negative_ids');
                const data=new win.FormData(field.form);
                check(field.value===(typ==='negativ'?'201, 202':'100, 200'), 'Edit fills not prefilled '+typ);
                check(data.get(field.name)===field.value && !data.has(typ==='negativ'?'negative_ids':'fill_ids'), 'Edit direction wrong '+typ);
                const hidden=new Promise(resolve => modal.addEventListener('hidden.bs.modal',resolve,{once:true}));
                instance.hide(); await hidden;
              }
            }
            if(narrow) {
              toggle.click(); await sleep(400);
              check(toggle.getAttribute('aria-expanded')==='false', 'Menu did not close '+width);
            }
            check(!win.previewErrors.length, win.previewErrors.join('; '));
            frame.remove();
          }
          document.getElementById('result').textContent='PASS';
        } catch(error) {document.getElementById('result').textContent='FAIL: '+error.message;}
      })();
    </script>'''.replace("PAGE", json.dumps(html).replace("<", "\\u003c"))
    assert _firefox_result(outer, assets, tmp_path) == "PASS"


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
            assert "css/custom.css?v=tablet-nav-color-1" in html
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
