"""Opt-in round trip of the manual polygon form against disposable PostGIS."""
import os
from pathlib import Path
import runpy

import psycopg2
import pytest

from app.routes import polygons as polygon_routes


@pytest.fixture(scope='module')
def polygon_database():
    if os.environ.get('ARCHEODB_TEST_POSTGRES') != '1':
        pytest.skip('Set ARCHEODB_TEST_POSTGRES=1 for disposable PostGIS tests')
    integration = Path(__file__).resolve().parents[2] / 'db/tests/test_spatial_integration.py'
    cluster = runpy.run_path(str(integration))['SpatialIntegrationTests']
    try:
        cluster.setUpClass()
        yield cluster
    finally:
        cluster.doClassCleanups()


def test_manual_form_builds_both_sides_and_protects_existing_gis_edits(client, monkeypatch, polygon_database):
    cluster = polygon_database
    monkeypatch.setattr(polygon_routes, 'get_terrain_connection', lambda _name: psycopg2.connect(
        dbname='01_Spatial', user='app_terrain_db', host=cluster.tmp.name, port=55447,
    ))
    with client.session_transaction() as state:
        state['selected_db'] = '01_Spatial'

    def submit(**fields):
        response = client.post('/polygons/new-manual', data={
            'polygon_name': 'manual', 'allocation_reason': 'other', **fields,
        })
        assert response.status_code == 302
        with client.session_transaction() as state:
            return state.pop('_flashes', [])

    flashes = submit(**{
        'top_range_from[]': ['1', '3'], 'top_range_to[]': ['2', '4'],
        'bottom_range_from[]': '5', 'bottom_range_to[]': '8',
    })
    assert flashes[-1][0] == 'success', flashes
    assert cluster.psql("""SELECT string_agg(geometry_role||':'||GeometryType(geom)||':'||ST_SRID(geom)||':'||ST_CoordDim(geom),',' ORDER BY geometry_role)
        FROM tab_entity_geometries WHERE ref_polygon='manual';""") == 'bottom:POLYGON:32633:3,top:POLYGON:32633:3'
    assert cluster.psql("SELECT ST_Z(ST_PointN(ST_ExteriorRing(geom_top),2)) FROM tab_polygons WHERE polygon_name='manual';") == '101'

    cluster.psql("UPDATE v_gis_polygon_z SET geom=ST_Translate(geom,0,0,5) WHERE ref_polygon='manual' AND geometry_role='bottom';",
                 user='editor@example.invalid')
    bottom_before = cluster.psql("SELECT ST_AsEWKT(geom_bottom) FROM tab_polygons WHERE polygon_name='manual';")

    # Leaving BOTTOM blank preserves its definition and the manual GIS geometry.
    flashes = submit(**{'top_range_from[]':'1', 'top_range_to[]':'4'})
    assert flashes[-1][0] == 'success', flashes
    assert cluster.psql("SELECT ST_AsEWKT(geom_bottom) FROM tab_polygons WHERE polygon_name='manual';") == bottom_before
    assert cluster.psql("SELECT pts_from,pts_to FROM tab_polygon_geopts_binding_bottom WHERE ref_polygon='manual';") == '5|8'

    # An unconfirmed rebuild rolls back the entire form, including its metadata.
    flashes = submit(notes='must roll back', **{'bottom_range_from[]':'5', 'bottom_range_to[]':'8'})
    assert flashes[-1][0] == 'danger', flashes
    assert cluster.psql("SELECT notes IS NULL FROM tab_polygons WHERE polygon_name='manual';") == 't'
    assert cluster.psql("SELECT ST_AsEWKT(geom_bottom) FROM tab_polygons WHERE polygon_name='manual';") == bottom_before

    flashes = submit(replace_geometry='yes', **{'bottom_range_from[]':'5', 'bottom_range_to[]':'8'})
    assert flashes[-1][0] == 'success', flashes
    assert cluster.psql("SELECT source_method,ST_Z(ST_PointN(ST_ExteriorRing(geom),1)) FROM tab_entity_geometries WHERE ref_polygon='manual' AND geometry_role='bottom';") == 'survey_points|100'

    flashes = submit(**{'top_range_from[]':'4', 'top_range_to[]':'1'})
    assert flashes[-1][0] == 'warning', flashes
    assert cluster.psql("SELECT pts_from,pts_to FROM tab_polygon_geopts_binding_top WHERE ref_polygon='manual';") == '1|4'
