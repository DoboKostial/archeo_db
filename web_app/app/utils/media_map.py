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
