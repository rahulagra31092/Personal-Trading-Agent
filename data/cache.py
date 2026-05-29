import sqlite3
import json
import time
from pathlib import Path

DB_PATH = Path(__file__).parent / "cache.db"

def init_db() -> None:
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS cache (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                expires_at REAL NOT NULL
            )
        """)

def get_cache(key: str) -> dict | None:
    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute(
            "SELECT value, expires_at FROM cache WHERE key = ?", (key,)
        ).fetchone()
        if row is None:
            return None
        value, expires_at = row
        if expires_at != 0 and expires_at < time.time():
            return None
        return json.loads(value)

def set_cache(key: str, value: dict, ttl_seconds: int = 3600) -> None:
    expires_at = time.time() + ttl_seconds if ttl_seconds > 0 else 0
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO cache (key, value, expires_at) VALUES (?, ?, ?)",
            (key, json.dumps(value), expires_at),
        )
