from __future__ import annotations

from app.services.quote_service import QuoteService
import time


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
