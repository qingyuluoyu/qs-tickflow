from __future__ import annotations

from datetime import date, datetime
from types import SimpleNamespace

import polars as pl

from app.market_time import (
    CN_TZ,
    MarketSession,
    resolve_market_as_of,
)


def test_preopen_uses_previous_completed_weekday_for_daily_data():
    result = resolve_market_as_of(datetime(2026, 8, 17, 9, 0, tzinfo=CN_TZ))

    assert result.session is MarketSession.PREOPEN
    assert result.current_date == date(2026, 8, 17)
    assert result.daily_date == date(2026, 8, 14)
    assert result.is_partial is False
    assert result.cutoff_time == "09:30:00"


def test_morning_and_lunch_allow_current_day_only_for_intraday_data():
    morning = resolve_market_as_of(datetime(2026, 8, 17, 10, 15, tzinfo=CN_TZ))
    lunch = resolve_market_as_of(datetime(2026, 8, 17, 12, 0, tzinfo=CN_TZ))

    assert morning.session is MarketSession.MORNING
    assert morning.daily_date == date(2026, 8, 14)
    assert morning.intraday_date == date(2026, 8, 17)
    assert morning.is_partial is True
    assert lunch.session is MarketSession.LUNCH
    assert lunch.daily_date == date(2026, 8, 14)
    assert lunch.intraday_date == date(2026, 8, 17)


def test_post_close_allows_current_day_complete_daily_bar():
    result = resolve_market_as_of(datetime(2026, 8, 17, 15, 1, tzinfo=CN_TZ))

    assert result.session is MarketSession.POST_CLOSE
    assert result.daily_date == date(2026, 8, 17)
    assert result.is_partial is False
    assert result.cutoff_time == "15:00:00"


def test_weekend_is_closed_and_keeps_last_weekday():
    result = resolve_market_as_of(datetime(2026, 8, 16, 11, 0, tzinfo=CN_TZ))

    assert result.session is MarketSession.CLOSED
    assert result.daily_date == date(2026, 8, 14)
    assert result.intraday_date is None
    assert result.is_partial is False


def test_minute_endpoint_falls_back_to_last_local_session_when_today_is_empty(monkeypatch):
    from app.api import kline

    current = resolve_market_as_of(datetime(2026, 8, 17, 10, 15, tzinfo=CN_TZ))
    monkeypatch.setattr(kline, "resolve_market_as_of", lambda: current)
    monkeypatch.setattr(
        kline.kline_sync,
        "fetch_minute_single",
        lambda *_args, **_kwargs: pl.DataFrame(),
    )

    class Repo:
        def resolve_asset_type(self, _symbol):
            return "stock"

        def execute_one(self, *_args, **_kwargs):
            return ("平安银行", 1_000_000.0, 800_000.0)

        def latest_minute_date(self, _symbol, asset_type="stock"):
            assert asset_type == "stock"
            return date(2026, 8, 14)

        def latest_daily_date(self):
            return date(2026, 8, 14)

        def get_minute(self, symbol, day, asset_type="stock"):
            if day == date(2026, 8, 17):
                return pl.DataFrame()
            assert (symbol, day, asset_type) == ("000001.SZ", date(2026, 8, 14), "stock")
            return pl.DataFrame([{
                "symbol": symbol,
                "datetime": datetime(2026, 8, 14, 15, 0),
                "close": 12.3,
            }])

    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(repo=Repo())))
    result = kline.get_minute(request, symbol="000001.SZ", trade_date=None)

    assert result["date"] == "2026-08-14"
    assert result["source"] == "local_fallback"
    assert result["market_as_of"]["session"] == "morning"


def test_minute_provider_response_is_reused_within_refresh_window(monkeypatch):
    from app.api import kline

    calls = {"count": 0}
    frame = pl.DataFrame([{
        "symbol": "000001.SZ",
        "datetime": datetime(2026, 8, 17, 10, 15),
        "close": 12.3,
    }])

    def fake_fetch(*_args, **_kwargs):
        calls["count"] += 1
        return frame

    monkeypatch.setattr(kline.kline_sync, "fetch_minute_single", fake_fetch)
    monkeypatch.setattr(kline.time, "monotonic", lambda: 100.0)
    kline._minute_live_cache.clear()

    first = kline._fetch_minute_cached("000001.SZ", date(2026, 8, 17), "stock")
    second = kline._fetch_minute_cached("000001.SZ", date(2026, 8, 17), "stock")

    assert calls["count"] == 1
    assert first.to_dicts() == second.to_dicts()
