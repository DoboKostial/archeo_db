from PIL import Image
import pytest
from datetime import date
import json

from app.routes import su as su_routes


SAMPLE_02_TEST_RELS = [
    (1, ">", 7),
    (7, ">", 8),
    (7, "<", 1),
    (8, ">", 9),
    (8, "<", 7),
    (9, ">", 11),
    (10, ">", 11),
    (4, ">", 10),
    (5, ">", 4),
    (5, ">", 1),
    (12, ">", 5),
    (2, ">", 12),
    (3, ">", 2),
    (6, ">", 4),
    (6, ">", 3),
]

SAMPLE_02_TEST_ROWS = [(sj_id, "deposit") for sj_id in range(1, 13)]


def _sample_harris_graph():
    graph, label_map, node_type_map, _dsu = su_routes._build_harris_matrix_data(
        SAMPLE_02_TEST_RELS,
        SAMPLE_02_TEST_ROWS,
    )
    return graph, label_map, node_type_map


def test_harris_matrix_builds_top_down_hasse_graph_from_02_test_sample():
    graph, _label_map, node_type_map = _sample_harris_graph()

    assert set(graph.edges()) == {
        (6, 3),
        (3, 2),
        (2, 12),
        (12, 5),
        (5, 1),
        (1, 7),
        (7, 8),
        (8, 9),
        (9, 11),
        (5, 4),
        (4, 10),
        (10, 11),
    }
    assert (6, 4) not in graph.edges()

    levels = su_routes._harris_levels(graph)
    assert levels[6] < levels[3] < levels[2] < levels[12] < levels[5]
    assert levels[5] < levels[1] < levels[7] < levels[8] < levels[9] < levels[11]
    assert levels[5] < levels[4] < levels[10] < levels[11]
    assert set(node_type_map.values()) == {"deposit"}


def test_harris_matrix_fallback_layout_preserves_sample_branches():
    graph, label_map, _node_type_map = _sample_harris_graph()

    positions = su_routes._fallback_harris_layout(graph, label_map)

    assert positions[6][1] > positions[3][1] > positions[2][1] > positions[12][1]
    assert positions[12][1] > positions[5][1]
    assert positions[1][0] < positions[4][0]
    assert positions[7][0] == pytest.approx(positions[1][0])
    assert positions[8][0] == pytest.approx(positions[7][0])
    assert positions[9][0] == pytest.approx(positions[8][0])
    assert positions[10][0] == pytest.approx(positions[4][0])


def test_harris_matrix_rejects_cycles():
    with pytest.raises(ValueError, match="cycle"):
        su_routes._build_harris_matrix_data(
            [(1, ">", 2), (2, ">", 1)],
            [(1, "deposit"), (2, "deposit")],
        )


def test_generate_harrismatrix_saves_non_blank_image(client, tmp_path, monkeypatch):
    class _Connection:
        def close(self):
            return None

    matrix_dir = tmp_path / "harrismatrix"
    monkeypatch.setattr(su_routes, "get_terrain_connection", lambda _dbname: _Connection())
    monkeypatch.setattr(
        su_routes,
        "fetch_stratigraphy_relations",
        lambda _conn: SAMPLE_02_TEST_RELS,
    )
    monkeypatch.setattr(
        su_routes,
        "get_all_sj_with_types",
        lambda _conn: SAMPLE_02_TEST_ROWS,
    )
    monkeypatch.setattr(
        su_routes,
        "get_hmatrix_dirs",
        lambda _dbname: (str(matrix_dir), None),
    )
    monkeypatch.setattr(su_routes, "_harris_matrix_layout", su_routes._fallback_harris_layout)

    with client.session_transaction() as session:
        session["selected_db"] = "02_test"

    response = client.post("/generate-harrismatrix")

    assert response.status_code == 302
    generated_files = list(matrix_dir.glob("*.png"))
    assert len(generated_files) == 1
    links_file = matrix_dir / f"{generated_files[0].name}.links.json"
    assert links_file.exists()
    assert json.loads(links_file.read_text(encoding="utf-8"))["areas"]

    image = Image.open(generated_files[0]).convert("RGB")
    pixels = image.getdata()
    assert image.size[0] > 100
    assert image.size[1] > 100
    assert any(pixel != (255, 255, 255) for pixel in pixels)


def test_harris_matrix_image_returns_clickable_su_and_object_areas(tmp_path):
    graph, label_map, node_type_map, dsu = su_routes._build_harris_matrix_data(
        SAMPLE_02_TEST_RELS,
        SAMPLE_02_TEST_ROWS,
    )
    positions = su_routes._fallback_harris_layout(graph, label_map)
    filepath = tmp_path / "matrix.png"

    areas = su_routes._save_harris_matrix_image(
        graph,
        positions,
        label_map,
        node_type_map,
        {"deposit": "#ADD8E6"},
        str(filepath),
        draw_objects=True,
        obj_rows=[(42, "wall", None)],
        sj_obj_rows=[(1, 42), (7, 42), (8, 42)],
        dsu=dsu,
    )

    assert filepath.exists()
    assert any(area["kind"] == "su" and area["id"] == 1 for area in areas)
    assert any(area["kind"] == "object" and area["id"] == 42 for area in areas)
    assert all(0 <= area["left"] <= 100 for area in areas)
    assert all(0 <= area["top"] <= 100 for area in areas)
    assert all(area["width"] > 0 and area["height"] > 0 for area in areas)


class _HarrisPageCursor:
    def __init__(self):
        self.query = ""

    def execute(self, query, _params=None):
        self.query = query

    def fetchall(self):
        return [("deposit", 2)]

    def fetchone(self):
        if "COUNT(DISTINCT ref_object)" in self.query:
            return (1,)
        if "COUNT(*) FROM tab_sj;" in self.query:
            return (2,)
        return (0,)

    def close(self):
        return None


class _HarrisPageConnection:
    def cursor(self):
        return _HarrisPageCursor()

    def close(self):
        return None


def test_harrismatrix_page_renders_clickable_overlay(client, monkeypatch):
    monkeypatch.setattr(su_routes, "get_terrain_connection", lambda _dbname: _HarrisPageConnection())
    monkeypatch.setattr(
        su_routes,
        "_load_harris_links",
        lambda _dbname, _image: [
            {
                "kind": "su",
                "id": 1,
                "ids": [1],
                "label": "1",
                "left": 10,
                "top": 20,
                "width": 5,
                "height": 4,
            }
        ],
    )

    with client.session_transaction() as session:
        session["selected_db"] = "02_test"
        session["harrismatrix_image"] = "matrix.png"

    response = client.get("/harrismatrix")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "hmatrix-image-wrap" in html
    assert "hmatrix-hotspot hmatrix-hotspot-su" in html
    assert 'data-hmatrix-id="1"' in html
    assert 'id="hmatrixEntityModal"' in html


class _DetailCursor:
    def __init__(self, row):
        self.row = row
        self.params = None

    def __enter__(self):
        return self

    def __exit__(self, _exc_type, _exc, _tb):
        return False

    def execute(self, _query, params=None):
        self.params = params

    def fetchone(self):
        return self.row


class _DetailConnection:
    def __init__(self, row):
        self.row = row

    def cursor(self):
        return _DetailCursor(self.row)

    def close(self):
        return None


def test_harrismatrix_su_detail_api_returns_entity_payload(client, monkeypatch):
    row = (
        7,
        "deposit",
        "floor layer",
        "occupation",
        date(2026, 8, 6),
        "author@example.invalid",
        True,
        False,
        80,
        3,
        "floor",
        "brown",
        "sharp",
        "sandy",
        "compact",
        "yes",
        "",
        False,
        "",
        "",
        "",
        "",
        "",
        "",
        "",
        None,
        None,
        None,
        ["P1"],
        [1],
        [8],
        [],
    )
    monkeypatch.setattr(su_routes, "get_terrain_connection", lambda _dbname: _DetailConnection(row))

    with client.session_transaction() as session:
        session["selected_db"] = "02_test"

    response = client.get("/harrismatrix/api/su/7")
    data = response.get_json()

    assert response.status_code == 200
    assert data["id_sj"] == 7
    assert data["description"] == "floor layer"
    assert data["ref_object"] == 3
    assert data["deposit"]["deposit_typ"] == "floor"
    assert data["above_ids"] == [1]
    assert data["below_ids"] == [8]


def test_harrismatrix_object_detail_api_returns_object_payload(client, monkeypatch):
    class _Connection:
        def close(self):
            return None

    monkeypatch.setattr(su_routes, "get_terrain_connection", lambda _dbname: _Connection())
    monkeypatch.setattr(
        su_routes,
        "q_get_object_with_sjs",
        lambda _conn, _object_id: (3, "wall", None, "north wall", [7, 8]),
    )
    monkeypatch.setattr(su_routes, "q_get_object_inhum_grave", lambda _conn, _object_id: None)

    with client.session_transaction() as session:
        session["selected_db"] = "02_test"

    response = client.get("/harrismatrix/api/object/3")
    data = response.get_json()

    assert response.status_code == 200
    assert data["id_object"] == 3
    assert data["object_typ"] == "wall"
    assert data["notes"] == "north wall"
    assert data["sj_ids"] == [7, 8]
