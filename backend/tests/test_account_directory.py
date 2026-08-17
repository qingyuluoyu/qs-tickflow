from pathlib import Path

from app.services.account_directory import AccountDirectoryCache
from app.services.account_store import AccountStore


def test_directory_cache_returns_preprocessed_metadata_without_secrets(tmp_path: Path):
    store = AccountStore(tmp_path)
    store.enter("张三", "一", "密码")
    store.enter("李四", "二", "密码")
    cache = AccountDirectoryCache(store, refresh_interval=60)

    total, rows = cache.page(offset=0, limit=1)

    assert total == 2
    assert len(rows) == 1
    assert {"password_hash", "password_salt"}.isdisjoint(rows[0])


def test_directory_cache_reports_health_and_keeps_last_snapshot_on_refresh_error(tmp_path: Path, monkeypatch):
    store = AccountStore(tmp_path)
    store.enter("张三", "一", "密码")
    cache = AccountDirectoryCache(store, refresh_interval=60)
    assert cache.refresh_now() is True
    healthy = cache.status()
    assert healthy["total"] == 1
    assert healthy["last_error"] is None
    assert healthy["stale"] is False

    def broken_list_users(*, offset, limit):
        raise OSError("temporary sqlite failure")

    monkeypatch.setattr(store, "list_users", broken_list_users)
    assert cache.refresh_now() is False
    degraded = cache.status()
    assert degraded["total"] == 1
    assert "temporary sqlite failure" in degraded["last_error"]
    assert degraded["stale"] is True
