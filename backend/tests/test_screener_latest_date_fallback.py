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
