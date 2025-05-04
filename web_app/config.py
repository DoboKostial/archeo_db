import os

class Config:
    # Auth DB
    AUTH_DB_NAME = "auth_db"
    AUTH_DB_USER = "app_terrain_db"
    AUTH_DB_PASSWORD = "" # add DB passwod here
    AUTH_DB_HOST = "localhost"
    AUTH_DB_PORT = 5432

    # Terrain DBs
    TERRAIN_DB_USER = "app_terrain_db"
    TERRAIN_DB_PASSWORD = "" # add DB password here
    TERRAIN_DB_HOST = "localhost" #or PostgreSQL host
    TERRAIN_DB_PORT = 5432 # or Your port where Postgres listens


    # Secret key pro JWT
    SECRET_KEY = "" # generate your own key for JWT token user for user session

    # log paths
    LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "../log")
    MAIN_LOG_PATH = os.path.join(LOG_DIR, "app_archeodb.log")
    SYNC_LOG_PATH = os.path.join(LOG_DIR, "synchronization.log")
    

    # administrator of app
    ADMIN_NAME = '' # admin of web aplication
    ADMIN_EMAIL = "" # admin mail
    

    #where are DB dumps stored? define backup abspath
    BACKUP_DIR = ""

    #absolute path for Harrismatrix images
    HARRISMATRIX_IMGS = ""

    #General folder for temporary uploading
    UPLOAD_FOLDER = ""
    
    #Define abspath for terrain images (photos)  
    TERR_FOTO_DIR = ""
    TERR_FOTO_THUMBS_DIR = os.path.join(TERR_FOTO_DIR, "thumbs")
