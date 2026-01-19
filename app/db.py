import os
import threading
from contextlib import contextmanager

import psycopg

_conn: psycopg.Connection | None = None
_lock = threading.RLock()


def _build_conninfo() -> str:
    return (
        f"host={os.getenv('DB_HOST')} "
        f"port={os.getenv('DB_PORT')} "
        f"dbname={os.getenv('DB_NAME')} "
        f"user={os.getenv('DB_USER')} "
        f"password={os.getenv('DB_PASSWORD')}"
    )


# Initialize ONE global database connection (no pool)
def init_db() -> None:
    global _conn
    if _conn is None:
        _conn = psycopg.connect(_build_conninfo())


def close_db() -> None:
    global _conn
    if _conn is not None:
        _conn.close()
        _conn = None


@contextmanager
def locked_conn():
    """
    Yield the single shared connection while holding a lock.
    This serializes DB access so concurrent API requests / worker iterations
    don't use the same connection simultaneously.
    """
    global _conn
    if _conn is None:
        raise RuntimeError("DB connection is not initialized (did you call init_db?)")

    with _lock:
        yield _conn


def get_conn():
    """
    FastAPI dependency: yields the shared connection under a lock for the
    duration of the request handler.
    """
    with locked_conn() as conn:
        yield conn
