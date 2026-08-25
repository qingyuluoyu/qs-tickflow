"""A股市场时间工具 — 固定北京时间 (UTC+8, 无夏令时)。

服务器/容器本地时区不可靠 (python:slim 镜像默认 UTC), 交易时段判断、
实时行情落盘日期等必须显式使用北京时间, 否则 Docker 部署时轮询窗口
与真实交易时段完全错开 (北京 9:15-15:05 = UTC 1:15-7:05)。
"""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from datetime import time as dt_time
from enum import StrEnum
from threading import RLock

CN_TZ = timezone(timedelta(hours=8))

# A 股交易时段 (北京时间): 上午 9:30-11:30 (120 分钟) + 下午 13:00-15:00 (120 分钟) = 240 分钟
_TRADING_TOTAL_MINUTES = 240
_MORNING_START = dt_time(9, 30)
_MORNING_END = dt_time(11, 30)
_AFTERNOON_START = dt_time(13, 0)
_AFTERNOON_END = dt_time(15, 0)

_calendar_lock = RLock()
_trading_calendar: frozenset[date] | None = None
_trading_calendar_source = "weekday_fallback"
_trading_calendar_start: date | None = None
_trading_calendar_end: date | None = None


class MarketSession(StrEnum):
    """A 股北京时间交易阶段。

    ``MORNING``/``AFTERNOON`` are continuous-auction windows. ``LUNCH`` is
    the midday break; ``PREOPEN`` and ``POST_CLOSE`` are closed for trades but
    are useful when deciding whether a daily candle is complete.
    """

    PREOPEN = "preopen"
    MORNING = "morning"
    LUNCH = "lunch"
    AFTERNOON = "afternoon"
    POST_CLOSE = "post_close"
    CLOSED = "closed"


@dataclass(frozen=True)
class MarketAsOf:
    """Resolved exchange date/cutoff used by current-data endpoints.

    ``daily_date`` is the last date whose daily bar is allowed in calculations.
    During a live session it intentionally remains the previous completed
    trading day; ``intraday_date`` carries the current date for minute/realtime
    data, which prevents partial daily candles from leaking into indicators.
    """

    current_date: date
    daily_date: date
    intraday_date: date | None
    session: MarketSession
    cutoff_time: str
    is_partial: bool
    observed_at: datetime


def _as_cn_datetime(value: datetime | None) -> datetime:
    """Normalize an optional timestamp to timezone-aware Beijing time."""
    current = value or datetime.now(CN_TZ)
    if current.tzinfo is None:
        return current.replace(tzinfo=CN_TZ)
    return current.astimezone(CN_TZ)


def set_trading_calendar(
    days: Iterable[date],
    *,
    source: str = "provider",
    coverage_start: date | None = None,
    coverage_end: date | None = None,
) -> None:
    """Install a validated exchange calendar for all cutoff calculations.

    The provider adapter owns fetching and normalising the calendar.  Keeping
    only the open-date set here makes the hot path deterministic and avoids a
    network request while resolving a request's market session.
    """
    valid = frozenset(day for day in days if isinstance(day, date))
    if not valid:
        raise ValueError("trading calendar must contain at least one date")
    range_start = coverage_start or min(valid)
    range_end = coverage_end or max(valid)
    if range_start > range_end:
        raise ValueError("trading calendar coverage is inverted")
    with _calendar_lock:
        global _trading_calendar, _trading_calendar_end, _trading_calendar_source, _trading_calendar_start
        _trading_calendar = valid
        _trading_calendar_source = str(source or "provider")
        _trading_calendar_start = range_start
        _trading_calendar_end = range_end


def clear_trading_calendar() -> None:
    """Clear the provider calendar and return to the safe weekday fallback."""
    with _calendar_lock:
        global _trading_calendar, _trading_calendar_end, _trading_calendar_source, _trading_calendar_start
        _trading_calendar = None
        _trading_calendar_source = "weekday_fallback"
        _trading_calendar_start = None
        _trading_calendar_end = None


def trading_calendar_source() -> str:
    with _calendar_lock:
        return _trading_calendar_source


def is_exchange_trading_day(value: date) -> bool:
    with _calendar_lock:
        calendar = _trading_calendar
        calendar_start = _trading_calendar_start
        calendar_end = _trading_calendar_end
    if calendar is None or (
        calendar_start is not None
        and calendar_end is not None
        and (value < calendar_start or value > calendar_end)
    ):
        return value.weekday() < 5
    return value in calendar


def _previous_trading_day(value: date) -> date:
    result = value - timedelta(days=1)
    # A-share calendars are finite but may include long closures.  The bound
    # prevents a malformed provider calendar from creating an infinite loop.
    for _ in range(370):
        if is_exchange_trading_day(result):
            return result
        result -= timedelta(days=1)
    return value - timedelta(days=1)


def resolve_market_as_of(
    now: datetime | None = None,
    *,
    is_trading_day: bool | None = None,
) -> MarketAsOf:
    """Resolve the safe A-share daily/intraday cutoff for ``now``.

    The optional ``is_trading_day`` argument is intended for an exchange
    calendar result. When omitted, weekends are treated as closed and
    weekdays follow the normal A-share schedule. A provider can pass ``False``
    for a weekday holiday without changing the time rules in this module.
    """
    observed = _as_cn_datetime(now)
    current_date = observed.date()
    weekday_open = is_exchange_trading_day(current_date)
    trading_day = weekday_open if is_trading_day is None else bool(is_trading_day)
    if not trading_day:
        return MarketAsOf(
            current_date=current_date,
            daily_date=_previous_trading_day(current_date),
            intraday_date=None,
            session=MarketSession.CLOSED,
            cutoff_time="00:00:00",
            is_partial=False,
            observed_at=observed,
        )

    current_time = observed.time()
    if current_time < _MORNING_START:
        return MarketAsOf(
            current_date=current_date,
            daily_date=_previous_trading_day(current_date),
            intraday_date=None,
            session=MarketSession.PREOPEN,
            cutoff_time=_MORNING_START.isoformat(),
            is_partial=False,
            observed_at=observed,
        )
    if current_time < _MORNING_END:
        session = MarketSession.MORNING
    elif current_time < _AFTERNOON_START:
        session = MarketSession.LUNCH
    elif current_time < _AFTERNOON_END:
        session = MarketSession.AFTERNOON
    else:
        return MarketAsOf(
            current_date=current_date,
            daily_date=current_date,
            intraday_date=current_date,
            session=MarketSession.POST_CLOSE,
            cutoff_time=_AFTERNOON_END.isoformat(),
            is_partial=False,
            observed_at=observed,
        )

    cutoff = current_time.replace(microsecond=0).isoformat()
    return MarketAsOf(
        current_date=current_date,
        daily_date=_previous_trading_day(current_date),
        intraday_date=current_date,
        session=session,
        cutoff_time=cutoff,
        is_partial=True,
        observed_at=observed,
    )


def cn_now() -> datetime:
    """当前北京时间 (带时区)。"""
    return datetime.now(CN_TZ)


def cn_today() -> date:
    """当前北京日期。"""
    return datetime.now(CN_TZ).date()


def latest_weekday(value: date) -> date:
    """Return the latest exchange trading date on or before ``value``."""
    result = value
    for _ in range(370):
        if is_exchange_trading_day(result):
            return result
        result -= timedelta(days=1)
    return value


def is_market_snapshot_stale(snapshot_date: date | None, current_date: date) -> bool:
    """Check daily freshness without flagging Friday data as stale on weekends."""
    if snapshot_date is None:
        return False
    expected = latest_weekday(current_date)
    return snapshot_date < expected


def trading_minutes_elapsed_from_dt(dt: datetime) -> float:
    """根据北京时间 datetime 计算当日已交易分钟数。

    交易时段: 9:30-11:30 (0~120) + 13:00-15:00 (120~240)。
    - 开盘前 = 0; 午休(11:30-13:00) = 120(保持上午累计); 收盘后 = 240。
    - 非交易日(周末) = 240 (视作全天, 避免量比被折算成 0)。
    """
    t = dt.time()
    if t < _MORNING_START:
        return 0.0
    if t < _MORNING_END:
        return (dt.hour * 60 + dt.minute - 9 * 60 - 30) + dt.second / 60.0
    if t < _AFTERNOON_START:
        return 120.0  # 午休, 保持上午累计
    if t < _AFTERNOON_END:
        return 120.0 + (dt.hour * 60 + dt.minute - 13 * 60) + dt.second / 60.0
    return float(_TRADING_TOTAL_MINUTES)


def trading_minutes_elapsed() -> float:
    """当前已交易分钟数 (基于服务端北京时间)。

    量比折算的兜底: 当行情 timestamp 缺失时用服务端时间。
    优先使用 trading_minutes_elapsed_from_ts (行情真实时间, 更准)。
    """
    return trading_minutes_elapsed_from_dt(cn_now())


def trading_minutes_elapsed_from_ts(ts_ms: int | float | None) -> float:
    """从行情时间戳(毫秒)计算当日已交易分钟数。

    优先使用此函数: 行情 timestamp 是真实成交时间, 比服务端时间更准
    (服务端时间含网络/限流延迟)。

    Args:
        ts_ms: 毫秒级 Unix 时间戳 (TickFlow SDK quote.timestamp / kline.timestamp)

    Returns:
        已交易分钟数 (0~240)。timestamp 为 None/无效时返回 240 (视作全天,
        避免量比被折算成 0)。
    """
    if not ts_ms:
        return float(_TRADING_TOTAL_MINUTES)
    try:
        dt = datetime.fromtimestamp(int(ts_ms) / 1000.0, tz=CN_TZ)
    except (ValueError, TypeError, OSError):
        return float(_TRADING_TOTAL_MINUTES)
    return trading_minutes_elapsed_from_dt(dt)
