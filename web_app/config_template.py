#this is tempalte config. Please edit 'XXX' values according Your needs

import os

class Config:
    # Auth DB
    AUTH_DB_NAME = "auth_db"
    AUTH_DB_USER = "app_terrain_db"
    AUTH_DB_PASSWORD = "XXX"
    AUTH_DB_HOST = "localhost"
    AUTH_DB_PORT = 5432

    # Terrain DBs
    TERRAIN_DB_USER = "app_terrain_db"
    TERRAIN_DB_PASSWORD = "XXX"
    TERRAIN_DB_HOST = "localhost"
    TERRAIN_DB_PORT = 5432


    # Secret key pro JWT
    SECRET_KEY = "XXX"

    # log paths
    APP_LOG = "XXX"
        

    # administrator of app
    ADMIN_NAME = 'Ďobo'
    ADMIN_EMAIL = "dobo@dobo.sk"
    

    #where are DB dumps stored? define backup abspath
    BACKUP_DIR = "XXX"

    #Images
    HARRISMATRIX_IMGS = "XXX"

    #General folder for temporary uploading
    UPLOAD_FOLDER = "XXX"

    # folders for graphic documentation
    TERR_FOTO_DIR = "XXX"
    TERR_FOTO_THUMBS_DIR = os.path.join(TERR_FOTO_DIR, "thumbs")
