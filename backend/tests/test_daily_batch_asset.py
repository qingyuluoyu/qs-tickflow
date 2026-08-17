"""daily-batch 混合资产分组测试。"""
import datetime as _dt

import polars as pl
import pytest

from app.tickflow.repository import DataStore, KlineRepository


@pytest.fixture()
def repo(tmp_path):
    return KlineRepository(DataStore(tmp_path))


def test_daily_batch_groups_index_symbols(repo, monkeypatch):
    from app.api import kline as kline_api

    calls = {"stock_batch": [], "index": []}

    def fake_stock_batch(symbols, start, end, columns=None):
        calls["stock_batch"].append(list(symbols))
        return pl.DataFrame()

    def fake_index_daily(symbol, start, end, columns=None):
        calls["index"].append(symbol)
        return pl.DataFrame({
            "symbol": [symbol], "date": [_dt.date(2026, 7, 24)],
            "open": [1.0], "high": [1.0], "low": [1.0], "close": [1.0], "volume": [1],
        })

    monkeypatch.setattr(repo, "get_daily_batch", fake_stock_batch)
    monkeypatch.setattr(repo, "get_index_daily", fake_index_daily)
    monkeypatch.setattr(repo, "get_index_symbol_set", lambda: {"000001.SH"})
    monkeypatch.setattr(repo, "get_etf_symbol_set", lambda: set())

    state = type("S", (), {"repo": repo})()
    req = type("R", (), {"app": type("A", (), {"state": state})()})()

    out = kline_api.get_daily_batch(req, {"symbols": ["600000.SH", "000001.SH"], "days": 12})
    assert calls["stock_batch"] == [["600000.SH"]]
    assert calls["index"] == ["000001.SH"]
    assert "000001.SH" in out["data"]


def test_index_daily_sync_passes_index_asset_type_to_provider(repo, monkeypatch):
    from app.services import index_sync
    from app.tickflow.capabilities import Cap, CapabilityLimits, CapabilitySet

    captured = {}
    monkeypatch.setattr(index_sync.preferences, "get_index_daily_batch_size", lambda: 100)
    monkeypatch.setattr(
        index_sync.kline_sync,
        "sync_daily_batch",
        lambda *args, **kwargs: captured.update(kwargs) or pl.DataFrame(),
    )

    index_sync.sync_and_persist_index_daily(
        repo,
        CapabilitySet({Cap.KLINE_DAILY_BATCH: CapabilityLimits(batch=100, rpm=100)}),
        symbols_override=["000001.SH"],
    )

    assert captured["asset_type"] == "index"


def test_atomic_parquet_write_retries_transient_windows_file_lock(tmp_path, monkeypatch):
    import app.tickflow.repository as repository_module

    out = tmp_path / "part.parquet"
    calls = 0
    original_replace = repository_module.os.replace

    def replace_with_one_lock(src, dst):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise PermissionError(5, "Access is denied", str(dst))
        return original_replace(src, dst)

    monkeypatch.setattr(repository_module.os, "replace", replace_with_one_lock)
    monkeypatch.setattr(repository_module.time, "sleep", lambda _seconds: None)

    KlineRepository._atomic_write_parquet(pl.DataFrame({"symbol": ["000001.SZ"]}), out)

    assert calls == 2
    assert pl.read_parquet(out).to_dicts() == [{"symbol": "000001.SZ"}]


def test_index_instrument_sync_uses_selected_custom_provider(repo, monkeypatch):
    from app.services import index_sync

    class Provider:
        def get_instruments(self, asset_type):
            return pl.DataFrame({
                "symbol": ["000001.SH"], "name": ["上证指数"], "code": ["000001"],
                "exchange": ["SH"], "asset_type": [asset_type], "source": ["teajoin"],
            })

    monkeypatch.setattr(index_sync.preferences, "get_daily_data_provider", lambda: "teajoin")
    monkeypatch.setattr("app.data_providers.custom.provider_has_dataset", lambda _name, dataset: dataset == "instruments")
    monkeypatch.setattr("app.data_providers.custom.get_provider", lambda _name: Provider())
    monkeypatch.setattr(index_sync, "get_client", lambda: (_ for _ in ()).throw(AssertionError("TickFlow must not be called")))

    assert index_sync.sync_index_instruments(repo, pull_index=True, pull_etf=False) == 1
    assert repo.get_index_instruments()["symbol"].to_list() == ["000001.SH"]
