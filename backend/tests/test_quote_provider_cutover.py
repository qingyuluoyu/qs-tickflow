from __future__ import annotations

import time
from datetime import date
from types import SimpleNamespace

import polars as pl

from app.services import quote_service
from app.services.quote_service import QuoteService


def test_selected_custom_provider_without_realtime_is_fail_closed(monkeypatch):
    service = QuoteService()

    monkeypatch.setattr(
        "app.services.preferences.get_realtime_data_provider",
        lambda: "teajoin",
    )
    monkeypatch.setattr(
        "app.data_providers.custom.provider_has_dataset",
        lambda name, dataset: False,
    )

    def unexpected_tickflow_client():
        raise AssertionError("selected custom provider must not call TickFlow")

    monkeypatch.setattr(
        "app.tickflow.client.get_paid_realtime_client",
        unexpected_tickflow_client,
    )

    service._fetch_full_market_quotes()

    status = service.status()
    assert status["realtime_provider"] == "teajoin"
    assert status["last_fetch_status"] == "provider_unavailable"
    assert status["symbol_count"] == 0


def test_empty_custom_realtime_snapshot_is_recorded_without_updating_timestamp(monkeypatch):
    service = QuoteService()

    monkeypatch.setattr(
        "app.services.preferences.get_realtime_data_provider",
        lambda: "teajoin",
    )
    monkeypatch.setattr(
        "app.data_providers.custom.provider_has_dataset",
        lambda name, dataset: name == "teajoin" and dataset == "realtime",
    )
    monkeypatch.setattr(
        "app.data_providers.custom.get_provider",
        lambda name: type("Provider", (), {"get_realtime": lambda self, **_: []})(),
    )

    service._fetch_full_market_quotes()

    status = service.status()
    assert status["realtime_provider"] == "teajoin"
    assert status["last_fetch_status"] == "empty"
    assert status["last_fetch_rows"] == 0
    assert status["last_fetch_ms"] is None


def test_custom_realtime_failure_does_not_consume_sina_overlay(monkeypatch):
    service = QuoteService()
    monkeypatch.setattr(
        "app.services.preferences.get_realtime_data_provider",
        lambda: "teajoin",
    )
    monkeypatch.setattr(
        "app.data_providers.custom.provider_has_dataset",
        lambda name, dataset: name == "teajoin" and dataset == "realtime",
    )
    monkeypatch.setattr(
        "app.data_providers.custom.get_provider",
        lambda _name: type(
            "Provider",
            (),
            {"get_realtime": lambda self, **_: (_ for _ in ()).throw(RuntimeError("upstream"))},
        )(),
    )
    monkeypatch.setattr(
        service,
        "_fetch_sina_overlay_fallback",
        lambda: (_ for _ in ()).throw(AssertionError("Sina must not be mixed into TeaJoin data")),
    )

    service._fetch_full_market_quotes()

    assert service.status()["last_fetch_status"] == "error"


def test_watchlist_custom_provider_never_falls_back_to_tickflow(monkeypatch):
    service = QuoteService()
    captured = {}

    monkeypatch.setattr(
        "app.services.preferences.get_realtime_data_provider",
        lambda: "teajoin",
    )
    monkeypatch.setattr(
        "app.services.preferences.get_realtime_watchlist_symbols",
        lambda: ["600000.SH"],
    )
    monkeypatch.setattr(
        "app.data_providers.custom.provider_has_dataset",
        lambda name, dataset: name == "teajoin" and dataset == "realtime",
    )
    def provider(_name):
        return type(
            "Provider",
            (),
            {"get_realtime": lambda self, **kwargs: captured.update(kwargs) or []},
        )()

    monkeypatch.setattr("app.data_providers.custom.get_provider", provider)

    def unexpected_tickflow_client():
        raise AssertionError("watchlist custom provider must not call TickFlow")

    monkeypatch.setattr(
        "app.tickflow.client.get_paid_realtime_client",
        unexpected_tickflow_client,
    )

    service._fetch_watchlist_quotes()

    status = service.status()
    assert status["realtime_provider"] == "teajoin"
    assert status["last_fetch_status"] == "empty"
    assert captured == {"symbols": ["600000.SH"]}


def test_watchlist_background_fetch_uses_all_account_symbols(monkeypatch):
    service = QuoteService()
    service._app_state = type(
        "AppState",
        (),
        {"monitor_runtime": type("Runtime", (), {"watchlist_symbols": lambda self: {"600000.SH", "000001.SZ"}})()},
    )()
    captured = {}

    monkeypatch.setattr(
        "app.services.preferences.get_realtime_data_provider",
        lambda: "teajoin",
    )
    monkeypatch.setattr(
        "app.services.preferences.get_realtime_watchlist_symbols",
        lambda: ["WRONG.SZ"],
    )
    monkeypatch.setattr(
        "app.data_providers.custom.provider_has_dataset",
        lambda name, dataset: name == "teajoin" and dataset == "realtime",
    )
    monkeypatch.setattr(
        "app.data_providers.custom.get_provider",
        lambda _name: type(
            "Provider",
            (),
            {"get_realtime": lambda self, **kwargs: captured.update(kwargs) or []},
        )(),
    )

    service._fetch_watchlist_quotes()

    assert set(captured["symbols"]) == {"600000.SH", "000001.SZ"}


def test_quote_status_marks_old_successful_snapshot_stale(monkeypatch):
    service = QuoteService()
    monkeypatch.setattr("app.services.preferences.get_realtime_data_provider", lambda: "teajoin")
    service._last_fetch_status = "success"
    service._last_fetch_rows = 10
    service._fetched_at = (time.time() - 120) * 1000
    service._interval = 6.0

    status = service.status()

    assert status["provider_health"]["state"] == "stale"
    assert status["snapshot_age_ms"] >= 100_000


def test_close_final_accepts_verified_current_daily_preload_without_realtime(monkeypatch):
    service = QuoteService()
    snapshot = SimpleNamespace(
        kind="teajoin.daily",
        snapshot_date=date(2026, 8, 24),
        frame=pl.DataFrame({"symbol": ["600000.SH"], "close": [10.0]}),
        market_as_of={"date_verified": True},
    )
    service._app_state = SimpleNamespace(
        market_overview_preloader=SimpleNamespace(snapshot=lambda: snapshot),
    )
    monkeypatch.setattr(quote_service, "cn_today", lambda: date(2026, 8, 24))

    def unexpected_realtime_fetch():
        raise AssertionError("verified close daily snapshot must stop realtime polling")

    monkeypatch.setattr(service, "_fetch_full_market_quotes", unexpected_realtime_fetch)

    assert service._fetch_quotes(final_phase="close_final") is True


def test_morning_final_does_not_accept_previous_daily_preload(monkeypatch):
    service = QuoteService()
    snapshot = SimpleNamespace(
        kind="teajoin.daily",
        snapshot_date=date(2026, 8, 24),
        frame=pl.DataFrame({"symbol": ["600000.SH"], "close": [10.0]}),
        market_as_of={"date_verified": True},
    )
    service._app_state = SimpleNamespace(
        market_overview_preloader=SimpleNamespace(snapshot=lambda: snapshot),
    )
    monkeypatch.setattr(quote_service, "cn_today", lambda: date(2026, 8, 24))
    calls = []
    monkeypatch.setattr(service, "_fetch_full_market_quotes", lambda: calls.append("realtime"))

    assert service._fetch_quotes(final_phase="morning_final") is False
    assert calls == ["realtime"]


def test_final_sync_failure_uses_bounded_backoff(monkeypatch):
    service = QuoteService()
    service._interval = 6.0
    key = (date(2026, 8, 24), "close")
    now = 1_000.0
    monkeypatch.setattr(quote_service.time, "time", lambda: now)
    monkeypatch.setattr(quote_service, "cn_today", lambda: date(2026, 8, 24))

    first_delay = service._schedule_final_retry(key)

    assert first_delay == 30.0
    assert service._final_sync_attempts[key] == 1
    assert service._final_sync_retry_at[key] == now + 30.0
    assert service._should_poll_for_phase("close_final") is False

    now += 31.0
    assert service._should_poll_for_phase("close_final") is True

    delays = [service._schedule_final_retry(key) for _ in range(8)]
    assert delays[-1] == 300.0
    assert all(delay <= 300.0 for delay in delays)
