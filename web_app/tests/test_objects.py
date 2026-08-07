from app.routes import archeo_objects as object_routes


class _Connection:
    def close(self):
        return None


def test_objects_page_renders_pagination_markup_for_existing_objects(client, monkeypatch):
    objects = [
        (idx, "wall", None, "", [idx, idx + 100])
        for idx in range(1, 13)
    ]

    monkeypatch.setattr(object_routes, "get_terrain_connection", lambda _dbname: _Connection())
    monkeypatch.setattr(object_routes, "_get_next_object_id", lambda _conn: 13)
    monkeypatch.setattr(object_routes, "_get_object_types", lambda _conn: ["wall"])
    monkeypatch.setattr(object_routes, "q_list_objects_with_sjs", lambda _conn: objects)

    with client.session_transaction() as session:
        session["selected_db"] = "02_test"

    response = client.get("/objects")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert 'id="objectsTable"' in html
    assert 'data-page-size="10"' in html
    assert 'id="objectsTableBody"' in html
    assert 'id="objectsPaginationWrap"' in html
    assert 'id="objectsPagination"' in html
    assert 'data-object-id="12"' in html
