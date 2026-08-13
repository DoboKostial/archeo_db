# This is a template config. Please edit 'XXX' values for your deployment.
# after editing values, 'mv config_template.py config.py'
# For support contact author: dobo@dobo.sk
class Config:

    APP_VERSION = "1.0.0"
    BASE_URL = "https://FQDN" # FQDN address of Your app
    MOBILE_API_BASE_URL = "https://FQDN/mobile_api/"  # FQDN address of mobile API used by Android app
    MOBILE_LOGIN_GRANT_SECONDS = 120  # Clamped to 30-300 seconds by the web app

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

    # Cookies are expected to be transported over HTTPS in production.
    SESSION_COOKIE_SECURE = True
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"

    # CSRF (Flask-WTF)
    WTF_CSRF_HEADERS = ["X-CSRFToken", "X-CSRF-Token"]

    # Administrator contact
    ADMIN_NAME = 'XXX'
    ADMIN_EMAIL = "XXX"

    # Outgoing email. Defaults preserve a local MTA setup on localhost:25.
    MAIL_SERVER = "localhost"
    MAIL_PORT = 25
    MAIL_USERNAME = ""
    MAIL_PASSWORD = ""
    MAIL_USE_TLS = False
    MAIL_USE_SSL = False
    MAIL_TIMEOUT = 10
    MAIL_DEFAULT_SENDER = ""  # fallback: ADMIN_EMAIL
    MAIL_REPLY_TO = ""  # fallback: ADMIN_EMAIL

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

    # Request and individual file limits.
    MAX_CONTENT_LENGTH = 128 * 1024 * 1024
    MAX_FORM_MEMORY_SIZE = 2 * 1024 * 1024
    MAX_UPLOAD_FILE_BYTES = 64 * 1024 * 1024
    MAX_TEXT_UPLOAD_BYTES = 8 * 1024 * 1024
    DIRECTORY_SIZE_CACHE_SECONDS = 300

    # General data directory (for graphics, binaries, ...), e.g. images, PDF
    DATA_DIR = "XXX"  # e.g. "/var/www/archeodb_web_app/data/"


    # Thumbnails – longer side in pixels (for gallery/detail).
    THUMB_MAX_SIDE = 256

    # Allowed extensions for graphic docu (lowercase):
    ALLOWED_EXTENSIONS = {"jpeg", "jpg", "png", "tiff", "pdf"}

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
        "application/pdf",
    }
    
    # This is for photo data (EXIFs) inserted into DB in json column.
    # JSON is a pot of rubbish so some limitation would be helpfull. If no idea what does it mean just leave as is. 
    # EXIF store mode: "compact" or "full"
    EXIF_STORE_MODE = "compact"
    # Security limit for JSON size (after serialization)
    EXIF_MAX_JSON_BYTES = 32768
