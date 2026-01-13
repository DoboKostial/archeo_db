# This is a template config. Please edit 'XXX' values for your deployment.
# after editing values, 'mv config_template.py config.py'
# For support contact author: dobo@dobo.sk
class Config:

    APP_VERSION = "1.0.0"
    BASE_URL = "https://FQDN" # FQDN address of Your app

    # Auth DB
    AUTH_DB_NAME = "XXX"
    AUTH_DB_USER = "XXX"
    AUTH_DB_PASSWORD = "XXX"
    AUTH_DB_HOST = "XXX"
    AUTH_DB_PORT = 5432 # or port Postgres listens

    # Terrain DBs
    TERRAIN_DB_USER = "XXX"
    TERRAIN_DB_PASSWORD = "XXX"
    TERRAIN_DB_HOST = "XXX"
    TERRAIN_DB_PORT = 5432 # or port Postgres listens

    # Secret key for JWT
    SECRET_KEY = "XXX"

    # CSRF (Flask-WTF)
    WTF_CSRF_HEADERS = ["X-CSRFToken", "X-CSRF-Token"]

    # Administrator contact
    ADMIN_NAME = 'XXX'
    ADMIN_EMAIL = "XXX"

    # === PATHS (define absolute paths for server!) ===

    # Single log file for whole app
    APP_LOG = "XXX"  # e.g. "/var/log/archeodb.log"
    LOG_LEVEL = "WARNING"  # change for "DEBUG", "WARNING", "ERROR"

    # while we do pg_dump for DB backups, lets provide direct path to pg_dump binary
    PGDUMP_PATH = "/usr/bin/pg_dump"

    # Directory for DB dumps/backups
    BACKUP_DIR = "XXX"  # e.g. "/var/backups/archeodb/"

    # Directory for file uploads
    UPLOAD_FOLDER = "XXX"  # e.g. "/var/www/archeodb_web_app/uploads/"

    # General data directory (for graphics, binaries, ...), e.g. images, PDF
    DATA_DIR = "XXX"  # e.g. "/var/www/archeodb_web_app/data/"


    # Thumbnails – longer side in pixels (for gallery/detail).
    THUMB_MAX_SIDE = 256

    # Allowed extensions for graphic docu (lowercase):
    ALLOWED_EXTENSIONS = {"jpeg", "jpg", "png", "tiff", "svg", "pdf"}

    # Mapping of types -> subfolders under DATA_DIR
    MEDIA_DIRS = {
        "photos": "photos",
        "sketches": "sketches",
        "drawings": "drawings",
        "photograms": "photograms",
    }

    # Allowed MIME – validating according content, not extension!
    ALLOWED_MIME = {
        "image/jpeg",
        "image/png",
        "image/tiff",
        "image/svg+xml",
        "application/pdf",
    }
    
    # This is for photo data (EXIFs) inserted into DB in json column.
    # JSON is a pot of rubbish so some limitation would be helpfull. If no idea what does it mean just leave as is. 
    # EXIF store mode: "compact" or "full"
    EXIF_STORE_MODE = "compact"
    # Security limit for JSON size (after serialization)
    EXIF_MAX_JSON_BYTES = 32768

