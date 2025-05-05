import subprocess
from datetime import datetime
import os
from config import Config
import psycopg2

def get_auth_connection():
    return psycopg2.connect(
        dbname=Config.AUTH_DB_NAME,
        user=Config.AUTH_DB_USER,
        password=Config.AUTH_DB_PASSWORD,
        host=Config.AUTH_DB_HOST,
        port=Config.AUTH_DB_PORT
    )

def get_terrain_connection(dbname):
    return psycopg2.connect(
        dbname=dbname,
        user=Config.TERRAIN_DB_USER,
        password=Config.TERRAIN_DB_PASSWORD,
        host=Config.TERRAIN_DB_HOST,
        port=Config.TERRAIN_DB_PORT
    )


# here the logic for DB backups - will be used in routes.py
def create_database_backup(dbname):
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    backup_filename = f"{dbname}_{timestamp}.backup"
    backup_path = os.path.join(Config.BACKUP_DIR, backup_filename)

    os.makedirs(Config.BACKUP_DIR, exist_ok=True)  # create folder if does not exists. Watch permissions

    subprocess.run(
        [
            'pg_dump',
            '-h', Config.AUTH_DB_HOST,
            '-U', Config.AUTH_DB_USER,
            '-d', dbname,
            '-Fc',
            '-f', backup_path
        ],
        check=True
    )

    return backup_path
