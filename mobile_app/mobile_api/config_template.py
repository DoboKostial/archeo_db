# Copy this file to config.py and adjust the values for your deployment.


class Config:
    APP_NAME = "ArcheoDB Mobile API"
    APP_VERSION = "0.1.0"

    HOST = "127.0.0.1"
    PORT = 5050
    DEBUG = False

    # A single Gunicorn worker shares this limiter state across its threads. Replace
    # with a Redis URI before increasing the worker count or adding API VMs.
    RATELIMIT_STORAGE_URI = "memory://"

    # auth_db access
    AUTH_DB_NAME = "auth_db"
    AUTH_DB_USER = "app_mobile_db"
    AUTH_DB_PASSWORD = "CHANGE_ME_MOBILE"
    AUTH_DB_HOST = "localhost"
    AUTH_DB_PORT = 5432

    # terrain DB access
    TERRAIN_DB_USER = "app_mobile_db"
    TERRAIN_DB_PASSWORD = "CHANGE_ME_MOBILE"
    TERRAIN_DB_HOST = "localhost"
    TERRAIN_DB_PORT = 5432

    # JWT signing for mobile access tokens issued by this service
    JWT_SECRET_KEY = "CHANGE_ME_MOBILE_API_SECRET"

    # Web stack integration for password reset links sent from mobile API.
    # This must exactly match web_app Config.SECRET_KEY. Mobile API derives the
    # same purpose-specific signing keys used by the web forgot-password flow.
    WEB_BASE_URL = "https://localhost.local"
    WEB_PASSWORD_RESET_SECRET_KEY = "CHANGE_ME_MATCH_WEB_SECRET"
    ADMIN_NAME = "CHANGE_ME_ADMIN"
    ADMIN_EMAIL = "CHANGE_ME_ADMIN_EMAIL"

    # Outgoing password-reset email. Use the same SMTP account as web_app.
    MAIL_SERVER = "localhost"
    MAIL_PORT = 25
    MAIL_USERNAME = ""
    MAIL_PASSWORD = ""
    MAIL_USE_TLS = False
    MAIL_USE_SSL = False
    MAIL_TIMEOUT = 10
    MAIL_DEFAULT_SENDER = ""  # fallback: ADMIN_EMAIL
    MAIL_REPLY_TO = ""  # fallback: ADMIN_EMAIL

    # Directory for file uploads
    UPLOAD_FOLDER = "CHANGE_ME_UPLOAD_FOLDER"  # e.g. "/var/www/archeodb_web_app/uploads/"

    # Request and upload limits. Nginx should use the same request-size limit.
    MAX_CONTENT_LENGTH = 128 * 1024 * 1024
    MAX_FORM_MEMORY_SIZE = 2 * 1024 * 1024
    MAX_UPLOAD_FILE_BYTES = 64 * 1024 * 1024
    MAX_TEXT_UPLOAD_BYTES = 8 * 1024 * 1024

    # Shared media storage. In production this should point to the same mounted
    # data directory used by the main stack.
    DATA_DIR = "CHANGE_ME_SHARED_DATA_DIR"  # e.g. "/var/www/archeodb_web_app/data/"
    MEDIA_DIRS = {
        "photos": "photos",
        "sketches": "sketches",
        "drawings": "drawings",
        "photograms": "photograms",
    }

    # Thumbnails – longer side in pixels (for gallery/detail).
    THUMB_MAX_SIDE = 256

    # Allowed extensions for graphic docu (lowercase):
    ALLOWED_EXTENSIONS = {"jpeg", "jpg", "png", "tiff", "svg", "pdf"}

    # Allowed MIME – validating according content, not extension!
    ALLOWED_MIME = {
        "image/jpeg",
        "image/png",
        "image/tiff",
        "image/svg+xml",
        "application/pdf",
    }

    # This is for photo data (EXIFs) inserted into DB in json column.
    # EXIF store mode: "compact" or "full"
    EXIF_STORE_MODE = "compact"
    # Security limit for JSON size (after serialization)
    EXIF_MAX_JSON_BYTES = 32768

    LOG_LEVEL = "INFO"
