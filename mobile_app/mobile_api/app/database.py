from contextlib import contextmanager

import psycopg2

from config import Config


def get_auth_connection():
    return psycopg2.connect(
        dbname=Config.AUTH_DB_NAME,
        user=Config.AUTH_DB_USER,
        password=Config.AUTH_DB_PASSWORD,
        host=Config.AUTH_DB_HOST,
        port=Config.AUTH_DB_PORT,
    )


def get_terrain_connection(dbname: str):
    return psycopg2.connect(
        dbname=dbname,
        user=Config.TERRAIN_DB_USER,
        password=Config.TERRAIN_DB_PASSWORD,
        host=Config.TERRAIN_DB_HOST,
        port=Config.TERRAIN_DB_PORT,
    )


@contextmanager
def auth_connection():
    conn = get_auth_connection()
    try:
        yield conn
    finally:
        conn.close()


@contextmanager
def terrain_connection(dbname: str):
    conn = get_terrain_connection(dbname)
    try:
        yield conn
    finally:
        conn.close()


@contextmanager
def terrain_transaction(dbname: str):
    """Connection with an explicit transaction: commits on success,
    rolls back on any exception, always closes."""
    conn = get_terrain_connection(dbname)
    conn.autocommit = False
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
