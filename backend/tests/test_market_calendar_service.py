from __future__ import annotations

from datetime import date, datetime

import polars as pl

from app.market_time import (
    CN_TZ,
    clear_trading_calendar,
    resolve_market_as_of,
    set_trading_calendar,
    trading_calendar_source,
)
from app.services.market_calendar import refresh_market_calendar


def test_refresh_market_calendar_installs_provider_open_days(monkeypatch):
    class Provider:
        def get_calendar(self, *_args, **_kwargs):
            return pl.DataFrame(
                {
                    "date": [date(2026, 8, 8), date(2026, 8, 14), date(2026, 8, 17)],
                    "is_open": [1, 1, 1],
                }
            )

    monkeypatch.setattr("app.services.preferences.get_daily_data_provider", lambda: "teajoin")
    monkeypatch.setattr(
        "app.data_providers.custom.provider_has_dataset",
        lambda name, dataset: name == "teajoin" and dataset == "calendar",
    )
    monkeypatch.setattr("app.data_providers.custom.get_provider", lambda _name: Provider())
    clear_trading_calendar()

    try:
        assert refresh_market_calendar(
            force=True,
            now=datetime(2026, 8, 17, 10, 0, tzinfo=CN_TZ),
        ) is True
        assert trading_calendar_source() == "teajoin.calendar"
        resolved = resolve_market_as_of()
        assert resolved is not None
    finally:
        clear_trading_calendar()


def test_provider_switch_does_not_reuse_prior_calendar(monkeypatch):
    set_trading_calendar([date(2026, 8, 14)], source="teajoin.calendar")
    monkeypatch.setattr("app.services.preferences.get_daily_data_provider", lambda: "tickflow")

    try:
        assert refresh_market_calendar(force=True) is False
        assert trading_calendar_source() == "weekday_fallback"
    finally:
        clear_trading_calendar()


def test_stale_provider_calendar_is_rejected(monkeypatch):
    class Provider:
        def get_calendar(self, *_args, **_kwargs):
            return pl.DataFrame({"date": [date(2026, 8, 14)], "is_open": [1]})

    monkeypatch.setattr("app.services.preferences.get_daily_data_provider", lambda: "teajoin")
    monkeypatch.setattr(
        "app.data_providers.custom.provider_has_dataset",
        lambda name, dataset: name == "teajoin" and dataset == "calendar",
    )
    monkeypatch.setattr("app.data_providers.custom.get_provider", lambda _name: Provider())
    clear_trading_calendar()

    try:
        assert refresh_market_calendar(
            force=True,
            now=datetime(2026, 8, 25, 10, 0, tzinfo=CN_TZ),
        ) is False
        assert trading_calendar_source() == "weekday_fallback"
    finally:
        clear_trading_calendar()
