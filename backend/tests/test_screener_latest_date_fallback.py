from __future__ import annotations

from datetime import date
from types import SimpleNamespace

from app.services.screener import ScreenerService


def test_latest_date_falls_back_to_raw_daily_data_when_enriched_cache_is_empty():
    repo = SimpleNamespace(
        get_enriched_latest_asset=lambda _asset_type: (None, None),
        enriched_latest_date=lambda: None,
        execute_one=lambda _sql: (None,),
        latest_daily_date=lambda: date(2026, 8, 18),
    )

    assert ScreenerService(repo).latest_date() == date(2026, 8, 18)


def test_resolve_date_uses_previous_available_trading_day():
    calls = []

    def execute_one(sql, params=None):
        calls.append((sql, params))
        return (date(2026, 8, 21),)

    repo = SimpleNamespace(execute_one=execute_one)

    assert ScreenerService(repo).resolve_date(date(2026, 8, 23)) == date(2026, 8, 21)
    assert calls and calls[0][1] == [date(2026, 8, 23)]
