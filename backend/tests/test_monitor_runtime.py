from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import time

import polars as pl

from app.services.account_store import AccountStore
from app.services.monitor_runtime import AccountMonitorRuntime
from app.services.quote_service import QuoteService
from app.services.user_context import current_user
from app.strategy import monitor_rules


def _rule(rule_id: str, symbol: str) -> dict:
    return monitor_rules.normalize({
        "id": rule_id,
        "name": rule_id,
        "type": "price",
        "scope": "symbols",
        "symbols": [symbol],
        "conditions": [{"field": "change_pct", "op": ">", "value": 0.01}],
    })


def test_account_monitor_runtime_loads_rules_into_isolated_engines(tmp_path: Path):
    store = AccountStore(tmp_path)
    first = store.enter("甲", "100", "密码")
    second = store.enter("乙", "200", "密码")
    assert first is not None and second is not None
    monitor_rules.save_one(store.workspace(first.user.id), _rule("a", "600000.SH"))
    monitor_rules.save_one(store.workspace(second.user.id), _rule("b", "000001.SZ"))

    runtime = AccountMonitorRuntime(
        account_store=store,
        shared_root=tmp_path,
        builtin_dir=tmp_path / "builtin",
        history_loader=lambda *_args: None,
        history_loader_etf=lambda *_args: None,
        sector_monitor_service=None,
    )
    runtime.refresh_now()

    first_engine = runtime.get(first.user.id)
    second_engine = runtime.get(second.user.id)
    assert first_engine is not None and second_engine is not None
    assert set(first_engine.rules) == {"a"}
    assert set(second_engine.rules) == {"b"}
    assert first_engine is not second_engine
    assert runtime.index_symbols() == set()


def test_account_monitor_runtime_unions_index_and_intraday_symbols(tmp_path: Path):
    store = AccountStore(tmp_path)
    account = store.enter("甲", "100", "密码")
    assert account is not None
    monitor_rules.save_one(store.workspace(account.user.id), monitor_rules.normalize({
        "id": "idx",
        "name": "指数",
        "type": "price",
        "asset_type": "index",
        "scope": "symbols",
        "symbols": ["000001.SH"],
        "conditions": [{"field": "change_pct", "op": ">", "value": 0.01}],
    }))

    runtime = AccountMonitorRuntime(
        account_store=store,
        shared_root=tmp_path,
        builtin_dir=tmp_path / "builtin",
        history_loader=lambda *_args: None,
        history_loader_etf=lambda *_args: None,
        sector_monitor_service=None,
    )
    runtime.refresh_now()

    assert runtime.index_symbols() == {"000001.SH"}
    assert runtime.has_asset_rules("index") is True
    assert runtime.has_asset_rules("etf") is False


def test_account_monitor_runtime_unions_watchlists_without_request_context(tmp_path: Path):
    store = AccountStore(tmp_path)
    first = store.enter("甲", "100", "密码")
    second = store.enter("乙", "200", "密码")
    assert first is not None and second is not None
    for account, symbols in (
        (first, ["600000.SH", "000001.SZ"]),
        (second, ["000001.SZ", "300001.SZ"]),
    ):
        user_data = store.workspace(account.user.id) / "user_data"
        user_data.mkdir(parents=True, exist_ok=True)
        pl.DataFrame({"symbol": symbols}).write_parquet(user_data / "watchlist.parquet")

    runtime = AccountMonitorRuntime(
        account_store=store,
        shared_root=tmp_path,
        builtin_dir=tmp_path / "builtin",
        history_loader=lambda *_args: None,
        history_loader_etf=lambda *_args: None,
        sector_monitor_service=None,
    )
    runtime.refresh_now()

    assert runtime.watchlist_symbols() == {"600000.SH", "000001.SZ", "300001.SZ"}


def test_quote_service_evaluates_each_account_under_its_own_context(tmp_path: Path):
    store = AccountStore(tmp_path)
    first = store.enter("甲", "100", "密码")
    second = store.enter("乙", "200", "密码")
    assert first is not None and second is not None
    monitor_rules.save_one(store.workspace(first.user.id), _rule("a", "600000.SH"))
    monitor_rules.save_one(store.workspace(second.user.id), _rule("b", "000001.SZ"))
    runtime = AccountMonitorRuntime(
        account_store=store,
        shared_root=tmp_path,
        builtin_dir=tmp_path / "builtin",
        history_loader=lambda *_args: None,
        history_loader_etf=lambda *_args: None,
        sector_monitor_service=None,
    )
    runtime.refresh_now()

    service = QuoteService()
    service._repo = SimpleNamespace(store=SimpleNamespace(data_dir=tmp_path))
    service._app_state = SimpleNamespace(monitor_runtime=runtime, monitor_engine=None)
    service.get_enriched_today = lambda: (pl.DataFrame(), None)
    seen: list[tuple[str, str, Path]] = []

    def fake_evaluate(_engine, _df, _date, _ready, owner_id):
        user = current_user()
        seen.append((owner_id, user.id if user else "", runtime.account_store.workspace(user.id)))
        return [], False

    service._evaluate_monitor_engine = fake_evaluate
    with patch.object(QuoteService, "_is_continuous_trading", return_value=True):
        service._evaluate_monitors(pl.DataFrame(), None)

    assert {row[0] for row in seen} == {first.user.id, second.user.id}
    assert {row[1] for row in seen} == {first.user.id, second.user.id}
    assert all(row[2].exists() for row in seen)


def test_account_monitor_runtime_refresh_failure_keeps_snapshot_and_reports_health(tmp_path: Path, monkeypatch):
    store = AccountStore(tmp_path)
    account = store.enter("甲", "100", "密码")
    assert account is not None
    runtime = AccountMonitorRuntime(
        account_store=store,
        shared_root=tmp_path,
        builtin_dir=tmp_path / "builtin",
        history_loader=lambda *_args: None,
        history_loader_etf=lambda *_args: None,
        sector_monitor_service=None,
        refresh_interval=0.01,
    )
    assert runtime.refresh_now() is True
    assert runtime.has_users()

    monkeypatch.setattr(store, "list_users", lambda **_kwargs: (_ for _ in ()).throw(OSError("db unavailable")))
    assert runtime.refresh_now() is False
    assert runtime.has_users()
    health = runtime.status()
    assert health["last_error"] == "OSError: db unavailable"
    assert health["stale"] is True


def test_account_monitor_runtime_records_evaluation_metrics(tmp_path: Path):
    store = AccountStore(tmp_path)
    account = store.enter("甲", "100", "密码")
    assert account is not None
    runtime = AccountMonitorRuntime(
        account_store=store,
        shared_root=tmp_path,
        builtin_dir=tmp_path / "builtin",
        history_loader=lambda *_args: None,
        history_loader_etf=lambda *_args: None,
        sector_monitor_service=None,
    )
    runtime.refresh_now()
    runtime.record_evaluation(account.user.id, duration_ms=12.5, running=True)
    runtime.record_evaluation(account.user.id, skipped=True)
    runtime.record_evaluation(account.user.id, duration_ms=3.0, error=True, running=False)
    health = runtime.status()
    assert health["evaluation_count"] == 2
    assert health["evaluation_error_count"] == 1
    assert health["evaluation_skipped_count"] == 1


def test_account_monitor_runtime_background_refresh_stops_cleanly(tmp_path: Path):
    store = AccountStore(tmp_path)
    runtime = AccountMonitorRuntime(
        account_store=store,
        shared_root=tmp_path,
        builtin_dir=tmp_path / "builtin",
        history_loader=lambda *_args: None,
        history_loader_etf=lambda *_args: None,
        sector_monitor_service=None,
        refresh_interval=0.01,
    )
    runtime.start()
    time.sleep(0.03)
    assert runtime.status()["running"] is True
    runtime.stop()
    assert runtime.status()["running"] is False
