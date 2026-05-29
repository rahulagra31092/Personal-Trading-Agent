import time
import pytest
from data.cache import get_cache, set_cache, init_db

@pytest.fixture(autouse=True)
def fresh_db(tmp_path, monkeypatch):
    monkeypatch.setattr("data.cache.DB_PATH", tmp_path / "test_cache.db")
    init_db()

def test_cache_miss_returns_none():
    assert get_cache("nonexistent_key") is None

def test_cache_hit_returns_value():
    set_cache("key1", {"price": 42.0}, ttl_seconds=60)
    assert get_cache("key1") == {"price": 42.0}

def test_expired_cache_returns_none():
    set_cache("key2", {"price": 99.0}, ttl_seconds=1)
    time.sleep(1.1)
    assert get_cache("key2") is None

def test_overwrite_existing_key():
    set_cache("key3", {"v": 1}, ttl_seconds=60)
    set_cache("key3", {"v": 2}, ttl_seconds=60)
    assert get_cache("key3") == {"v": 2}
