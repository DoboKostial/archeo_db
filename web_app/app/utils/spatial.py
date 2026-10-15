"""Spatial file validation and Shapefile serialization, without database access."""
from io import BytesIO
import math
import zipfile

import shapefile


WORLD_EXTENSIONS = {'.jgw', '.jpgw', '.tfw', '.tifw', '.pgw', '.pngw', '.wld'}
SOURCE_EXTENSIONS = {'.dwg', '.dxf', '.gpkg', '.zip', '.geojson', '.json', '.obj', '.ply', '.stl'}


def validate_world_file(data):
    """A world file is six finite affine coefficients, one per line."""
    try:
        lines = data.decode('utf-8-sig').splitlines()
        values = [float(line.strip()) for line in lines if line.strip()]
    except (ValueError, UnicodeError):
        raise ValueError('A world file must contain six numeric coefficients.') from None
    if len(values) != 6 or not all(math.isfinite(v) for v in values):
        raise ValueError('A world file must contain six finite numeric coefficients.')
    if values[0] * values[3] - values[1] * values[2] == 0:
        raise ValueError('The world file transformation must be invertible.')


def _has_z(coords):
    while coords and isinstance(coords[0], (list, tuple)):
        coords = coords[0]
    return len(coords) == 3


def _ring(coords, clockwise):
    area = sum(a[0]*b[1]-b[0]*a[1] for a,b in zip(coords, coords[1:]))
    return list(reversed(coords)) if (area < 0) != clockwise else coords


def shapefile_zip(features, projections):
    """Split incompatible types/dimensions into layers and preserve XYZ coordinates."""
    groups = {}
    for feature in features:
        geom = feature['geometry']
        z = _has_z(geom['coordinates'])
        key = (geom['type'], z, feature['srid'])
        groups.setdefault(key, []).append(feature)
    result = BytesIO()
    with zipfile.ZipFile(result, 'w', zipfile.ZIP_DEFLATED) as archive:
        for (kind, z, srid), rows in groups.items():
            base = f'{kind.lower()}_{"z" if z else "xy"}_{srid}'
            streams = {ext: BytesIO() for ext in ('shp', 'shx', 'dbf')}
            types = {'Point':shapefile.POINT, 'MultiPoint':shapefile.MULTIPOINT,
                     'LineString':shapefile.POLYLINE, 'MultiLineString':shapefile.POLYLINE,
                     'Polygon':shapefile.POLYGON, 'MultiPolygon':shapefile.POLYGON}
            writer = shapefile.Writer(**streams, shapeType=types[kind]+(10 if z else 0), encoding='utf-8')
            for name, width in [('geom_id',20), ('entity',16), ('entity_id',150), ('role',24), ('source',24)]:
                writer.field(name, 'C', size=width)
            writer.field('proxy', 'L')
            for row in rows:
                coords = row['geometry']['coordinates']
                if kind == 'Point':
                    (writer.pointz if z else writer.point)(*coords)
                elif kind == 'MultiPoint':
                    (writer.multipointz if z else writer.multipoint)(coords)
                elif kind in ('LineString','MultiLineString'):
                    (writer.linez if z else writer.line)([coords] if kind=='LineString' else coords)
                else:
                    polygons = [coords] if kind=='Polygon' else coords
                    rings = [_ring(ring, i==0) for poly in polygons for i,ring in enumerate(poly)]
                    (writer.polyz if z else writer.poly)(rings)
                writer.record(str(row['id_geometry']),row['kind'],row['entity_id'],row['geometry_role'],row['source_method'],row['is_proxy'])
            writer.close()
            for ext, stream in streams.items():
                archive.writestr(f'{base}.{ext}', stream.getvalue())
            archive.writestr(f'{base}.cpg', 'UTF-8')
            if projections.get(srid):
                archive.writestr(f'{base}.prj', projections[srid])
        archive.writestr('README.txt', 'ArcheoDB spatial representations. Layers use project coordinates; Z is preserved.\n'
                         'proxy=T denotes an approximate representation. Native CAD/GIS attachments are not included.\n')
    result.seek(0)
    return result
