from __future__ import annotations

from datetime import date

import polars as pl

from app.services.market_overview_preloader import (
    DashboardSnapshot,
    MarketOverviewPreloader,
    _normalise_realtime_frame,
    make_dashboard_snapshot_fetcher,
)


def _snapshot(kind: str, status: str, value: float) -> DashboardSnapshot:
    return DashboardSnapshot(
        provider="teajoin",
        kind=kind,
        status=status,
        snapshot_date=date(2026, 8, 17),
        frame=pl.DataFrame([{"symbol": "000001.SZ", "close": value}]),
        fetched_at_ms=float(value),
        error=None,
    )


def test_preloader_keeps_last_valid_snapshot_and_records_empty_refresh():
    calls = []

    def fetch():
        calls.append(len(calls))
        return (
            _snapshot("teajoin.realtime", "success", 12.3)
            if len(calls) == 1
            else DashboardSnapshot.empty("teajoin", "empty")
        )

    preloader = MarketOverviewPreloader(fetch, interval_s=30)

    first = preloader.refresh_once()
    second = preloader.refresh_once()

    assert first.status == "success"
    assert second.status == "empty"
    cached = preloader.snapshot()
    assert cached is not None
    assert cached.frame["close"].item() == 12.3
    assert cached.kind == "teajoin.realtime"
    assert cached.status == "empty"
    assert cached.fetched_at_ms == 12.3


def test_preloader_refresh_is_single_flight():
    calls = 0

    def fetch():
        nonlocal calls
        calls += 1
        return _snapshot("teajoin.daily", "success", 12.3)

    preloader = MarketOverviewPreloader(fetch, interval_s=30)
    assert preloader.refresh_once().status == "success"
    assert calls == 1


def test_dashboard_snapshot_fetcher_is_callable_when_provider_has_no_realtime(monkeypatch):
    monkeypatch.setattr("app.services.preferences.get_realtime_data_provider", lambda: "tickflow")
    monkeypatch.setattr("app.services.preferences.get_daily_data_provider", lambda: "tickflow")
    fetch = make_dashboard_snapshot_fetcher()

    result = fetch()

    assert result.status == "provider_unavailable"
    assert result.frame.is_empty()


def test_dashboard_realtime_rates_are_normalized_to_percent():
    frame = _normalise_realtime_frame([{
        "symbol": "000001.SZ",
        "last_price": 12.3,
        "turnover_rate": 0.0315,
    }])

    assert frame["close"].item() == 12.3
    assert frame["turnover_rate"].item() == 3.15
