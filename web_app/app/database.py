import subprocess
from datetime import datetime
import os
from config import Config
import psycopg2
import tarfile
import gzip
import shutil
from io import BytesIO

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
    os.makedirs(Config.BACKUP_DIR, exist_ok=True)

    # --- 1. pg_dump gzip backup ---
    dump_filename = f"{dbname}_{timestamp}.backup"
    dump_path = os.path.join(Config.BACKUP_DIR, dump_filename)
    gz_dump_path = f"{dump_path}.gz"

    # Dump DB
    subprocess.run(
        [
            'pg_dump',
            '-h', Config.AUTH_DB_HOST,
            '-U', Config.AUTH_DB_USER,
            '-d', dbname,
            '-Fc',
            '-f', dump_path
        ],
        check=True
    )

    # Gzip the dump
    with open(dump_path, 'rb') as f_in, gzip.open(gz_dump_path, 'wb') as f_out:
        shutil.copyfileobj(f_in, f_out)
    os.remove(dump_path)

    # --- 2. gzip of datafolder of content data (images etc...) ---
    data_dir_path = os.path.join(Config.DATA_DIR, dbname)
    tar_path = os.path.join(Config.BACKUP_DIR, f"{dbname}_files_{timestamp}.tar.gz")
    with tarfile.open(tar_path, "w:gz") as tar:
        tar.add(data_dir_path, arcname=dbname)

    return gz_dump_path, tar_path
