# web_app/app/utils/media_map.py
# mapping types of docu to tables and aid tables

MEDIA_TABLES = {
    "photos": {
        "table": "tab_photos",
        "id_col": "id_photo",
        "extra_cols": ["photo_typ", "datum", "author", "notes"], 
    },
    "sketches": {
        "table": "tab_sketches",
        "id_col": "id_sketch",
        "extra_cols": ["sketch_typ", "author", "datum", "notes"],
    },
    "drawings": {
        "table": "tab_drawings",
        "id_col": "id_drawing",
        "extra_cols": ["author", "datum", "notes"],
    },
    "photograms": {
        "table": "tab_photograms",
        "id_col": "id_photogram",
        "extra_cols": ["photogram_typ", "ref_sketch", "notes"],
    },
}

# Relations SU ↔ media (table columns)
LINK_TABLES_SJ = {
    "photos":      {"table": "tabaid_photo_sj",       "fk_media": "ref_photo",     "fk_sj": "ref_sj"},
    "sketches":    {"table": "tabaid_sj_sketch",     "fk_media": "ref_sketch",    "fk_sj": "ref_sj"},
    "drawings":    {"table": "tabaid_sj_drawings",   "fk_media": "ref_drawing",   "fk_sj": "ref_sj"},
    "photograms":  {"table": "tabaid_photogram_sj",   "fk_media": "ref_photogram", "fk_sj": "ref_sj"},
}

# Relations polygon ↔ media (table columns)
LINK_TABLES_POLYGON = {
    "photos":      {"table": "tabaid_polygon_photos",       "fk_media": "ref_photo",     "fk_polygon": "ref_polygon"},
    "sketches":    {"table": "tabaid_polygon_sketches",     "fk_media": "ref_sketch",    "fk_polygon": "ref_polygon"},
    "photograms":  {"table": "tabaid_polygon_photograms",   "fk_media": "ref_photogram", "fk_polygon": "ref_polygon"},
}

# Relations section ↔ media (table columns)
LINK_TABLES_SECTION = {
    "photos":      {"table": "tabaid_section_photos",      "fk_media": "ref_photo",     "fk_section": "ref_section"},
    "sketches":    {"table": "tabaid_section_sketches",    "fk_media": "ref_sketch",    "fk_section": "ref_section"},
    "drawings":    {"table": "tabaid_section_drawings",    "fk_media": "ref_drawing",   "fk_section": "ref_section"},
    "photograms":  {"table": "tabaid_section_photograms",  "fk_media": "ref_photogram", "fk_section": "ref_section"},
}

# Relations finds ↔ media (table columns)
LINK_TABLES_FINDS = {
    "photos":      {"table": "tabaid_finds_photos",      "fk_media": "ref_photo",     "fk_find": "ref_find"},
    "sketches":    {"table": "tabaid_finds_sketches",    "fk_media": "ref_sketch",    "fk_find": "ref_find"},
}

# Relations samples ↔ media (table columns)
LINK_TABLES_SAMPLES = {
    "photos":      {"table": "tabaid_samples_photos",      "fk_media": "ref_photo",     "fk_sample": "ref_sample"},
    "sketches":    {"table": "tabaid_samples_sketches",    "fk_media": "ref_sketch",    "fk_sample": "ref_sample"},
}
