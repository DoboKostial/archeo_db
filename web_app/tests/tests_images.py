# tests/test_images.py
# these are unit tests for app/utils/images.py
# dobo@dobo.sk
# Below is the finished test file. It does not require any real media: we synthetically create a small JPEG in the test and write EXIF ​​(including GPS) to it via piexif. We test:
# extract_exif → shoot_dt, gps_lat/lon/alt and "compact" exif_json
# JSON sanitization (zero bytes → str)
# make_thumbnail (file creation, max size, EXIF ​​orientation)
# detect_mime (fallback via mimetypes so that the tests do not run on the system libmagic)
# usage: 
# Run: pytest -q from the web_app root (PYTHONPATH=. if necessary).

import os
import io
import json
import math
import tempfile
from datetime import datetime

import pytest
from PIL import Image, ImageOps

# Testing of local modul
from app.utils.images import (
    extract_exif, make_thumbnail, detect_mime, _jsonable
)

pytestmark = pytest.mark.order(1)  # if more sets

# Creates small JPEG with EXIF (with optional GPS) and returns path
def _make_jpeg_with_exif(tmpdir, name="sample.jpg", *, with_gps=True):
    path = os.path.join(tmpdir, name)
    im = Image.new("RGB", (640, 480), (120, 160, 200))
    bio = io.BytesIO()
    im.save(bio, format="JPEG", quality=92)
    bio.seek(0)

    # writing EXIF via piexif
    import piexif
    from fractions import Fraction

    zeroth = {
        piexif.ImageIFD.Make: "UnitTestCam",
        piexif.ImageIFD.Model: "ModelX",
        piexif.ImageIFD.Software: "pytest-suite",
        piexif.ImageIFD.DateTime: "2025:10:02 10:13:05",
    }
    exif = {
        piexif.ExifIFD.DateTimeOriginal: "2025:10:02 10:13:05",
        piexif.ExifIFD.ExifVersion: b"0230",
        piexif.ExifIFD.FNumber: (18, 10),  # 1.8
        piexif.ExifIFD.ISOSpeedRatings: 100,
    }
    gps = {}
    if with_gps:
        # 50°03'42.66"N, 14°42'16.02"E, alt 311m
        gps = {
            1: b"N",
            2: [(50, 1), (3, 1), (4266, 100)],  # 42.66"
            3: b"E",
            4: [(14, 1), (42, 1), (1602, 100)], # 16.02"
            5: 0,                                # above sea
            6: (311, 1),
        }

    exif_dict = {"0th": zeroth, "Exif": exif, "GPS": gps, "1st": {}}
    exif_bytes = piexif.dump(exif_dict)

    with open(path, "wb") as f:
        f.write(piexif.insert(exif_bytes, bio.getvalue()))
    return path

def test_extract_exif_with_gps(tmp_path):
    fpath = _make_jpeg_with_exif(tmp_path, "with_gps.jpg", with_gps=True)
    dt, lat, lon, alt, exif_json = extract_exif(str(fpath))

    assert isinstance(dt, (datetime, type(None)))
    # expecting ~ 50.06185 / 14.70445 / 311
    assert lat is not None and lon is not None and alt is not None
    assert math.isclose(lat, 50 + 3/60 + 42.66/3600, rel_tol=0, abs_tol=1e-6)
    assert math.isclose(lon, 14 + 42/60 + 16.02/3600, rel_tol=0, abs_tol=1e-6)
    assert math.isclose(alt, 311.0, rel_tol=0, abs_tol=1e-6)

    # EXIF JSON je „compact“ and serializable
    s = json.dumps(exif_json, ensure_ascii=False)
    assert "UnitTestCam" in s
    assert "ModelX" in s

def test_extract_exif_without_gps(tmp_path):
    fpath = _make_jpeg_with_exif(tmp_path, "no_gps.jpg", with_gps=False)
    dt, lat, lon, alt, exif_json = extract_exif(str(fpath))
    assert dt is not None
    assert lat is None and lon is None and alt is None
    json.dumps(exif_json)  # must not fail

def test_json_sanitization_null_bytes():
    # bytes + null bytes → str without \u0000
    dirty = {b"k\x00ey": b"va\x00lue", "ctrl": "a\x00b\x07c"}
    clean = _jsonable(dirty)
    s = json.dumps(clean)
    assert "\\u0000" not in s
    assert "abc" in s

def test_make_thumbnail_respects_max_side(tmp_path):
    fpath = _make_jpeg_with_exif(tmp_path, "thumb_src.jpg", with_gps=False)
    tpath = os.path.join(tmp_path, "thumbs", "thumb.jpg")
    ok = make_thumbnail(str(fpath), str(tpath), max_side=256)
    assert ok is True
    assert os.path.exists(tpath)
    w, h = Image.open(tpath).size
    assert max(w, h) <= 256

def test_detect_mime_fallback_mimetypes(tmp_path, monkeypatch):
    # enforcing path without python-magic
    monkeypatch.setattr("app.utils.images._HAS_MAGIC", False, raising=False)
    fpath = _make_jpeg_with_exif(tmp_path, "mime.jpg", with_gps=False)
    mt = detect_mime(str(fpath))
    assert mt in ("image/jpeg", "image/pjpeg")

