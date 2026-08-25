from __future__ import annotations

from datetime import date, datetime

from app.market_time import (
    CN_TZ,
    MarketSession,
    clear_trading_calendar,
    resolve_market_as_of,
    set_trading_calendar,
)


def test_resolve_market_as_of_uses_provider_calendar_for_weekday_holiday():
    set_trading_calendar(
        {date(2026, 8, 14), date(2026, 8, 17)},
        source="teajoin.calendar",
        coverage_start=date(2026, 8, 14),
        coverage_end=date(2026, 8, 18),
    )
    try:
        result = resolve_market_as_of(datetime(2026, 8, 17, 10, 0, tzinfo=CN_TZ))
        assert result.session is MarketSession.MORNING
        assert result.daily_date == date(2026, 8, 14)

        holiday = resolve_market_as_of(datetime(2026, 8, 18, 10, 0, tzinfo=CN_TZ))
        assert holiday.session is MarketSession.CLOSED
        assert holiday.daily_date == date(2026, 8, 17)
    finally:
        clear_trading_calendar()


def test_calendar_range_outside_provider_window_uses_weekday_fallback():
    set_trading_calendar(
        {date(2026, 8, 20), date(2026, 8, 21)},
        source="teajoin.calendar",
        coverage_start=date(2026, 8, 20),
        coverage_end=date(2026, 8, 21),
    )
    try:
        result = resolve_market_as_of(datetime(2026, 8, 24, 10, 0, tzinfo=CN_TZ))
        assert result.session is MarketSession.MORNING
        assert result.daily_date == date(2026, 8, 21)
    finally:
        clear_trading_calendar()
