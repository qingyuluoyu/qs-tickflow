"""Cached exchange calendar refresh for safe market cutoffs."""
from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timedelta

from app.market_time import CN_TZ, clear_trading_calendar, set_trading_calendar

logger = logging.getLogger(__name__)

_CACHE_TTL_S = 6 * 60 * 60.0
_RETRY_TTL_S = 5 * 60.0
_lock = threading.RLock()
_last_refresh_monotonic = 0.0
_last_success = False
_last_provider_name: str | None = None


def refresh_market_calendar(*, force: bool = False, now: datetime | None = None) -> bool:
    """Refresh the configured provider calendar without blocking every request.

    A failed refresh never clears the last known calendar.  The weekday
    fallback remains available when no provider advertises a calendar dataset.
    """
    global _last_refresh_monotonic, _last_provider_name, _last_success
    from app.data_providers import custom as custom_sources
    from app.services import preferences

    provider_name = preferences.get_daily_data_provider()
    current = time.monotonic()
    with _lock:
        provider_changed = provider_name != _last_provider_name
        if provider_changed:
            _last_provider_name = provider_name
            _last_refresh_monotonic = 0.0
            _last_success = False
        ttl = _CACHE_TTL_S if _last_success else _RETRY_TTL_S
        if not force and current - _last_refresh_monotonic < ttl:
            return _last_success
        _last_refresh_monotonic = current
    if provider_changed:
        # A calendar belongs to its provider.  Do not keep using TeaJoin's
        # holiday set after a runtime provider switch.
        clear_trading_calendar()

    try:
        if provider_name == "tickflow" or not custom_sources.provider_has_dataset(
            provider_name, "calendar"
        ):
            with _lock:
                _last_success = False
            return False
        provider = custom_sources.get_provider(provider_name)
        loader = getattr(provider, "get_calendar", None)
        if not callable(loader):
            with _lock:
                _last_success = False
            return False
        observed = now or datetime.now(CN_TZ)
        if observed.tzinfo is None:
            observed = observed.replace(tzinfo=CN_TZ)
        observed = observed.astimezone(CN_TZ)
        frame = loader(
            observed - timedelta(days=370),
            observed + timedelta(days=370),
            exchange="SSE",
        )
        if frame is None or frame.is_empty() or not {"date", "is_open"}.issubset(frame.columns):
            raise ValueError("calendar_empty_or_missing_fields")
        calendar_dates = frame.get_column("date").drop_nulls()
        if calendar_dates.is_empty():
            raise ValueError("calendar_has_no_dates")
        observed_date = observed.date()
        if calendar_dates.max() < observed_date:
            raise ValueError("calendar_stale")
        if calendar_dates.min() > observed_date - timedelta(days=7):
            raise ValueError("calendar_history_window_too_short")
        days = {
            row["date"]
            for row in frame.to_dicts()
            if row.get("date") is not None and int(row.get("is_open") or 0) == 1
        }
        if not days:
            raise ValueError("calendar_has_no_open_days")
        set_trading_calendar(
            days,
            source=f"{provider_name}.calendar",
            coverage_start=calendar_dates.min(),
            coverage_end=calendar_dates.max(),
        )
        with _lock:
            _last_success = True
        return True
    except Exception as exc:
        logger.warning("market calendar refresh failed: %s", type(exc).__name__)
        with _lock:
            _last_success = False
        return False
