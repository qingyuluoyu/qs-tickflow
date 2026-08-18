import time
from pathlib import Path

import polars as pl

from app.services import alert_store, preferences, watchlist
from app.services.user_context import UserIdentity, reset_current_user, set_current_user
from app.strategy import config as strategy_config
from app.strategy import custom_signals, monitor_rules


def _bind(root: Path, user_id: str):
    from app.services.account_store import AccountStore

    result = AccountStore(root).enter(user_id, f"{user_id}-phone", "password")
    assert result is not None
    return (
        set_current_user(
            UserIdentity(result.user.id, result.user.name, result.user.phone),
            root / "users" / result.user.id,
        ),
        result.user.id,
    )


def test_watchlist_and_preferences_use_the_authenticated_workspace(monkeypatch, tmp_path: Path):
    from app.config import settings

    monkeypatch.setattr(settings, "data_dir", tmp_path)
    first, alice_id = _bind(tmp_path, "alice")
    try:
        watchlist.add("600000.SH")
        preferences.save({"nav_order": ["/watchlist"]})
    finally:
        reset_current_user(first)

    second, bob_id = _bind(tmp_path, "bob")
    try:
        assert watchlist.list_symbols() == []
        assert preferences.load() == {}
        watchlist.add("000001.SZ")
    finally:
        reset_current_user(second)

    alice_file = tmp_path / "users" / alice_id / "user_data" / "watchlist.parquet"
    bob_file = tmp_path / "users" / bob_id / "user_data" / "watchlist.parquet"
    assert pl.read_parquet(alice_file)["symbol"].to_list() == ["600000.SH"]
    assert pl.read_parquet(bob_file)["symbol"].to_list() == ["000001.SZ"]


def test_strategies_signals_monitors_and_alerts_are_isolated_by_workspace(tmp_path: Path):
    alice_root = tmp_path / "users" / "alice"
    bob_root = tmp_path / "users" / "bob"
    now_ms = int(time.time() * 1000)

    strategy_config.save_override(alice_root, "shared_strategy", {"threshold": 1})
    strategy_config.save_override(bob_root, "shared_strategy", {"threshold": 2})
    custom_signals.save_one(alice_root, {"id": "alice_signal", "name": "甲信号"})
    custom_signals.save_one(bob_root, {"id": "bob_signal", "name": "乙信号"})
    monitor_rules.save_one(alice_root, {"id": "alice_rule", "name": "甲规则"})
    monitor_rules.save_one(bob_root, {"id": "bob_rule", "name": "乙规则"})
    alert_store.append(alice_root, {"ts": now_ms, "source": "alice"})
    alert_store.append(bob_root, {"ts": now_ms + 1, "source": "bob"})

    assert strategy_config.load_override(alice_root, "shared_strategy") == {"threshold": 1}
    assert strategy_config.load_override(bob_root, "shared_strategy") == {"threshold": 2}
    assert [row["id"] for row in custom_signals.load_all(alice_root)] == ["alice_signal"]
    assert [row["id"] for row in custom_signals.load_all(bob_root)] == ["bob_signal"]
    assert [row["id"] for row in monitor_rules.load_all(alice_root)] == ["alice_rule"]
    assert [row["id"] for row in monitor_rules.load_all(bob_root)] == ["bob_rule"]
    assert [row["source"] for row in alert_store.list_recent(alice_root)] == ["alice"]
    assert [row["source"] for row in alert_store.list_recent(bob_root)] == ["bob"]
