import subprocess
from datetime import datetime
import os
from config import Config
import psycopg2
import tarfile
import gzip
import shutil
from app.logger import logger


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

    # --- 1. pg_dump ---
    dump_filename = f"{dbname}_{timestamp}.backup"
    dump_path = os.path.join(Config.BACKUP_DIR, dump_filename)
    gz_dump_path = f"{dump_path}.gz"

    env = os.environ.copy()
    env["PGPASSWORD"] = Config.AUTH_DB_PASSWORD

    logger.info(f"Starting pg_dump for DB '{dbname}' into '{dump_path}'")

    result = subprocess.run(
        [
            Config.PGDUMP_PATH,
            '-h', Config.AUTH_DB_HOST,
            '-U', Config.AUTH_DB_USER,
            '-d', dbname,
            '-Fc',
            '-f', dump_path
        ],
        check=True,
        capture_output=True,
        text=True,
        env=env
    )

    logger.info(f"pg_dump stdout: {result.stdout.strip()}")
    if result.stderr.strip():
        logger.warning(f"pg_dump stderr: {result.stderr.strip()}")

    # gzip dump
    with open(dump_path, 'rb') as f_in, gzip.open(gz_dump_path, 'wb') as f_out:
        shutil.copyfileobj(f_in, f_out)
    os.remove(dump_path)

    logger.info(f"Gzipped dump created at '{gz_dump_path}'")

    # --- 2. Tar data directory ---
    data_dir_path = os.path.join(Config.DATA_DIR, dbname)
    gz_files_path = os.path.join(Config.BACKUP_DIR, f"{dbname}_files_{timestamp}.tar.gz")

    logger.info(f"Creating tar.gz of data directory '{data_dir_path}'")

    with tarfile.open(gz_files_path, "w:gz") as tar:
        tar.add(data_dir_path, arcname=dbname)

    logger.info(f"Data directory archive created at '{gz_files_path}'")

    return gz_dump_path, gz_files_path
