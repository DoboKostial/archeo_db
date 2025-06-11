# This is a tempialte config. Please edit 'XXX' values for your deployment.

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

    # Secret key for JWT
    SECRET_KEY = "XXX"

    # Administrator contact
    ADMIN_NAME = 'Ďobo'
    ADMIN_EMAIL = "dobo@dobo.sk"

    # === PATHS (define absolute paths for server!) ===

    # Single log file for whole app
    APP_LOG = "XXX"  # e.g. "/var/www/archeodb_web_app/log/app_archeodb.log"

    # Directory for DB dumps/backups
    BACKUP_DIR = "XXX"  # e.g. "/var/backups/archeodb/"

    # Directory for file uploads
    UPLOAD_FOLDER = "XXX"  # e.g. "/var/www/archeodb_web_app/uploads/"

    # General data directory (for graphics, binaries, ...), e.g. images, PDF
    DATA_DIR = "XXX"  # e.g. "/var/www/archeodb_web_app/data/"

