from html.parser import HTMLParser

import pytest
from flask import render_template, url_for

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
