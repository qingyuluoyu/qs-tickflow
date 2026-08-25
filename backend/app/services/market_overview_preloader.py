"""Background market snapshots used only by the market dashboard.

The dashboard must not make every page request wait for a provider round trip.
This service keeps the last valid provider snapshot and records the latest
realtime outcome separately, so an empty TeaJoin realtime response cannot be
mistaken for a current market snapshot.
"""
from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta
from datetime import time as clock_time

import polars as pl

from app.market_time import (
    MarketSession,
    cn_today,
    resolve_market_as_of,
    trading_calendar_source,
)

logger = logging.getLogger(__name__)

# daily 兜底连续失败计数 — 不稳定源退避日志用
_daily_fallback_fail_count = 0


def _reset_daily_fallback_fail_count() -> None:
    global _daily_fallback_fail_count
    _daily_fallback_fail_count = 0

_CORE_INDEX_SYMBOLS = ("000001.SH", "399001.SZ", "399006.SZ", "000680.SH")
_SETTLED_DAILY_REFRESH_S = 15 * 60.0
_MIN_DAILY_UNIVERSE_COVERAGE = 0.90


@dataclass(frozen=True)
class DashboardSnapshot:
    provider: str
    kind: str
    status: str
    snapshot_date: date | None
    frame: pl.DataFrame
    fetched_at_ms: float | None
    error: str | None
    # Number of rows returned by the realtime request in this refresh cycle.
    # This is intentionally separate from ``frame`` because a daily fallback
    # can contain thousands of rows while realtime is empty or unavailable.
    realtime_rows: int = 0
    # Core index daily rows are fetched in the same background cycle as the
    # stock snapshot.  Keeping them together prevents the sidebar and the
    # overview cards from making independent provider calls and observing
    # different dates.
    index_frame: pl.DataFrame = field(default_factory=pl.DataFrame)
    # Exchange cutoff metadata is kept with the warmed frame so the HTTP
    # request can report exactly which session/date produced the snapshot.
    market_as_of: dict[str, object] = field(default_factory=dict)

    @classmethod
    def empty(cls, provider: str, status: str, error: str | None = None) -> DashboardSnapshot:
        return cls(
            provider=provider,
            kind="persisted.enriched",
            status=status,
            snapshot_date=None,
            frame=pl.DataFrame(),
            fetched_at_ms=None,
            error=error,
            market_as_of={},
        )


class MarketOverviewPreloader:
    """Single-flight, non-blocking background snapshot refresher."""

    def __init__(
        self,
        fetcher: Callable[[], DashboardSnapshot],
        *,
        interval_s: float = 30.0,
    ) -> None:
        self._fetcher = fetcher
        self._interval_s = max(1.0, float(interval_s))
        self._lock = threading.RLock()
        self._refresh_lock = threading.Lock()
        self._snapshot: DashboardSnapshot | None = None
        self._snapshot_fingerprint: tuple | None = None
        self._snapshot_generation = 0
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def _copy(self, snapshot: DashboardSnapshot | None) -> DashboardSnapshot | None:
        if snapshot is None:
            return None
        return replace(
            snapshot,
            frame=snapshot.frame.clone(),
            index_frame=snapshot.index_frame.clone(),
        )

    def snapshot(self) -> DashboardSnapshot | None:
        with self._lock:
            return self._copy(self._snapshot)

    @staticmethod
    def _frame_fingerprint(frame: pl.DataFrame) -> tuple[int, int, int]:
        if frame is None or frame.is_empty():
            return (0, 0, 0)
        row_hash = frame.select(sorted(frame.columns)).hash_rows(seed=0)
        return (frame.height, frame.width, int(row_hash.sum() or 0))

    @classmethod
    def _fingerprint(cls, snapshot: DashboardSnapshot) -> tuple:
        return (
            snapshot.provider,
            snapshot.kind,
            snapshot.status,
            snapshot.snapshot_date,
            snapshot.error,
            snapshot.realtime_rows,
            cls._frame_fingerprint(snapshot.frame),
            cls._frame_fingerprint(snapshot.index_frame),
        )

    def _install_locked(self, snapshot: DashboardSnapshot) -> None:
        fingerprint = self._fingerprint(snapshot)
        if fingerprint != self._snapshot_fingerprint:
            self._snapshot_generation += 1
            self._snapshot_fingerprint = fingerprint
        self._snapshot = snapshot

    def status(self) -> dict[str, object]:
        """Return lightweight metadata without cloning the full market frame."""
        with self._lock:
            snapshot = self._snapshot
            return {
                "snapshot_generation": self._snapshot_generation,
                "snapshot_date": (
                    snapshot.snapshot_date.isoformat()
                    if snapshot is not None and snapshot.snapshot_date is not None
                    else None
                ),
                "snapshot_kind": snapshot.kind if snapshot is not None else None,
                "snapshot_status": snapshot.status if snapshot is not None else "warming",
            }

    def refresh_once(self) -> DashboardSnapshot | None:
        """Refresh once; concurrent callers never run duplicate provider calls."""
        if not self._refresh_lock.acquire(blocking=False):
            return self.snapshot()
        try:
            candidate = self._fetcher()
            if not isinstance(candidate, DashboardSnapshot):
                raise TypeError("dashboard snapshot fetcher returned an invalid result")
            with self._lock:
                previous = self._snapshot
                if candidate.frame is not None and not candidate.frame.is_empty():
                    self._install_locked(candidate)
                elif previous is not None and not previous.frame.is_empty():
                    # Keep prices/rankings from the last valid snapshot, but
                    # replace status so the UI exposes the current failure.
                    self._install_locked(replace(
                        previous,
                        status=candidate.status,
                        fetched_at_ms=(
                            candidate.fetched_at_ms
                            if candidate.fetched_at_ms is not None
                            else previous.fetched_at_ms
                        ),
                        error=candidate.error,
                        realtime_rows=candidate.realtime_rows,
                    ))
                else:
                    self._install_locked(candidate)
                return self._copy(self._snapshot)
        except Exception as exc:
            logger.warning("dashboard snapshot preload failed: %s", type(exc).__name__)
            with self._lock:
                previous = self._snapshot
                if previous is not None and not previous.frame.is_empty():
                    self._install_locked(replace(
                        previous,
                        status="error",
                        fetched_at_ms=time.time() * 1000,
                        error=type(exc).__name__,
                        realtime_rows=0,
                    ))
                else:
                    self._install_locked(
                        DashboardSnapshot.empty("unknown", "error", type(exc).__name__)
                    )
                return self._copy(self._snapshot)
        finally:
            self._refresh_lock.release()

    def start(self) -> None:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop.clear()
            self._thread = threading.Thread(
                target=self._run,
                name="dashboard-market-preload",
                daemon=True,
            )
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=max(2.0, self._interval_s + 1.0))
        self._thread = None

    def _run(self) -> None:
        while not self._stop.is_set():
            self.refresh_once()
            if self._stop.wait(self._interval_s):
                return


def _is_current_realtime_snapshot(snapshot: DashboardSnapshot | None) -> bool:
    """Return whether a snapshot can safely represent the current trading day."""
    return bool(
        snapshot is not None
        and snapshot.status == "success"
        and snapshot.kind.endswith(".realtime")
        and snapshot.realtime_rows > 0
        and snapshot.snapshot_date == cn_today()
    )


def make_dashboard_failover_fetcher(
    primary_fetcher: Callable[[], DashboardSnapshot],
    fallback_fetcher: Callable[[], DashboardSnapshot],
    *,
    allow_cross_source_fallback: bool = True,
) -> Callable[[], DashboardSnapshot]:
    """Prefer a configured provider, optionally allowing a display-only fallback.

    A configured provider may remain reachable but return an empty intraday
    response.  During that failure mode the dashboard must use the existing
    keyless Sina snapshot instead of displaying yesterday's completed daily
    partition as today's market state.  A fallback is accepted only when it
    has passed the same current-day realtime boundary; otherwise the primary
    result is retained for the closed-session daily path and diagnostics.
    """
    last_failure: tuple[str, str, str | None] | None = None

    def fetch() -> DashboardSnapshot:
        nonlocal last_failure
        primary: DashboardSnapshot | None = None
        try:
            primary = primary_fetcher()
        except Exception as exc:
            failure = ("primary", "error", type(exc).__name__)
            if failure != last_failure:
                logger.warning("dashboard primary snapshot unavailable; trying Sina: %s", failure[2])
                last_failure = failure

        if _is_current_realtime_snapshot(primary):
            last_failure = None
            return primary

        # TeaJoin is the authoritative source for production calculations.
        # Strict mode exposes the primary failure instead of mixing vendors.
        if not allow_cross_source_fallback:
            return primary if primary is not None else DashboardSnapshot.empty(
                "primary", "provider_unavailable", "primary_snapshot_unavailable"
            )

        try:
            fallback = fallback_fetcher()
        except Exception as exc:
            if primary is not None:
                return primary
            return DashboardSnapshot.empty("sina", "error", type(exc).__name__)

        if _is_current_realtime_snapshot(fallback):
            if primary is not None:
                failure = (primary.provider, primary.status, primary.error)
                if failure != last_failure:
                    logger.warning(
                        "dashboard provider %s returned no current realtime snapshot (%s); using Sina failover",
                        primary.provider,
                        primary.status,
                    )
                    last_failure = failure
            return fallback

        return primary if primary is not None else fallback

    return fetch


def _normalise_realtime_frame(records: list[dict]) -> pl.DataFrame:
    if not records:
        return pl.DataFrame()
    frame = pl.DataFrame(records)
    if "symbol" not in frame.columns:
        return pl.DataFrame()
    if "close" not in frame.columns and "last_price" in frame.columns:
        frame = frame.with_columns(pl.col("last_price").alias("close"))
    if "close" not in frame.columns:
        return pl.DataFrame()
    if "date" not in frame.columns:
        frame = frame.with_columns(pl.lit(cn_today()).cast(pl.Date).alias("date"))
    else:
        frame = frame.with_columns(pl.col("date").cast(pl.Date, strict=False).alias("date"))
        if frame.get_column("date").null_count() > 0:
            # An explicit but unparsable provider date is unsafe to infer as
            # today. Mixed valid/null dates are equally unsafe because the
            # undated rows would otherwise be relabelled as current.
            return pl.DataFrame()
    numeric = [
        "close", "last_price", "prev_close", "open", "high", "low", "volume",
        "amount", "change_pct", "change_amount", "amplitude", "turnover_rate",
    ]
    present = [column for column in numeric if column in frame.columns]
    if present:
        frame = frame.with_columns(
            [pl.col(column).cast(pl.Float64, strict=False).alias(column) for column in present]
        )
    frame = frame.filter(pl.col("symbol").is_not_null() & pl.col("close").is_not_null())
    if frame.is_empty():
        return pl.DataFrame()
    # The provider contract stores realtime rates as decimals (0.0315 =
    # 3.15%), while the dashboard/enriched response exposes percentages.
    # Convert once at this boundary so activity cards use the same unit for
    # realtime and daily-derived snapshots.
    if "turnover_rate" in frame.columns:
        frame = frame.with_columns(
            (pl.col("turnover_rate") * 100.0).alias("turnover_rate")
        )
    return frame


def _daily_snapshot_rejection(
    frame: pl.DataFrame,
    target_date: date,
    expected_symbols: set[str] | None = None,
    *,
    min_coverage: float = _MIN_DAILY_UNIVERSE_COVERAGE,
) -> str | None:
    """Return a stable rejection code for an unsafe completed daily frame."""
    if frame is None or frame.is_empty():
        return "empty"
    required = {"symbol", "date", "open", "high", "low", "close", "volume", "amount"}
    if not required.issubset(frame.columns):
        return "missing_fields"
    working = frame
    if working.schema.get("date") != pl.Date:
        working = working.with_columns(pl.col("date").cast(pl.Date, strict=False).alias("date"))
    if any(working.get_column(column).null_count() for column in required):
        return "null_fields"
    if working.filter(pl.col("date") != pl.lit(target_date).cast(pl.Date)).height:
        return "mixed_dates"
    if working.height != working.get_column("symbol").n_unique():
        return "duplicate_symbols"
    invalid_ohlc = working.filter(
        (pl.col("high") < pl.max_horizontal("open", "close", "low"))
        | (pl.col("low") > pl.min_horizontal("open", "close", "high"))
        | (pl.col("volume") < 0)
        | (pl.col("amount") < 0)
    )
    if not invalid_ohlc.is_empty():
        return "invalid_values"
    if expected_symbols:
        actual = set(working.get_column("symbol").cast(pl.Utf8).to_list())
        coverage = len(actual & expected_symbols) / len(expected_symbols)
        if coverage < max(0.0, min(1.0, float(min_coverage))):
            return "partial_universe"
    return None


def _align_index_frame_to_date(frame: pl.DataFrame, target_date: date) -> pl.DataFrame:
    """Keep only index symbols that have a quote on ``target_date``.

    Index data is fetched in a separate provider request from the stock
    snapshot.  A provider can publish the stock partition before the index
    partition (or return only a subset of symbols), so blindly retaining the
    last index rows can create a mixed-date dashboard.  Fail closed for a
    symbol without a target-day row while retaining its previous close for
    change calculations.
    """
    if frame is None or frame.is_empty() or not {"symbol", "date"}.issubset(frame.columns):
        return pl.DataFrame()
    if frame.schema.get("date") != pl.Date:
        frame = frame.with_columns(pl.col("date").cast(pl.Date, strict=False).alias("date"))
    frame = frame.filter(pl.col("symbol").is_not_null() & pl.col("date").is_not_null())
    if frame.is_empty():
        return pl.DataFrame()

    aligned: list[pl.DataFrame] = []
    for symbol in frame.get_column("symbol").unique().to_list():
        rows = (
            frame.filter(
                (pl.col("symbol") == symbol)
                & (pl.col("date") <= pl.lit(target_date).cast(pl.Date))
            )
            .sort("date", descending=True)
        )
        if rows.is_empty() or rows.get_column("date")[0] != target_date:
            continue
        aligned.append(rows.head(2))
    if not aligned:
        return pl.DataFrame()
    return pl.concat(aligned, how="diagonal_relaxed").sort(["symbol", "date"])


def _complete_core_index_frame(frame: pl.DataFrame, target_date: date) -> pl.DataFrame:
    """Return a date-aligned frame only when every core index is present."""
    aligned = _align_index_frame_to_date(frame, target_date)
    if aligned.is_empty():
        return aligned
    current_symbols = set(
        aligned.filter(pl.col("date") == pl.lit(target_date).cast(pl.Date))
        .get_column("symbol")
        .to_list()
    )
    if not set(_CORE_INDEX_SYMBOLS).issubset(current_symbols):
        return pl.DataFrame()
    return aligned.filter(pl.col("symbol").is_in(_CORE_INDEX_SYMBOLS))


def make_dashboard_snapshot_fetcher(
    *,
    daily_refresh_s: float = 30.0,
    expected_stock_symbols_loader: Callable[[], list[str]] | None = None,
) -> Callable[[], DashboardSnapshot]:
    """Build the production TeaJoin snapshot fetcher.

    Realtime is attempted only during A-share continuous/settlement sessions.
    The daily snapshot is refreshed independently for pre-open, post-close and
    closed sessions so a stale realtime response cannot be relabelled as today.
    """
    last_daily: DashboardSnapshot | None = None
    last_index_frame = pl.DataFrame()
    last_index_fetched_at_ms: float | None = None

    def _latest_daily(provider, asset_type: str) -> pl.DataFrame:
        """Read a latest snapshot while keeping test/custom providers compatible."""
        market_asof = resolve_market_as_of()
        # ``daily_date`` is already resolved against the current session: it is
        # the previous completed day before/within a session and today's day
        # only after the close boundary.  Do not use the natural calendar date
        # directly, otherwise weekends/holidays can be queried as trade dates.
        target_date = market_asof.daily_date
        # Keep deterministic callers that monkeypatch ``cn_today`` without
        # replacing the clock object compatible; production clocks always
        # have matching current dates.
        if market_asof.current_date != cn_today():
            target_date = cn_today()
        if asset_type == "index":
            batch_loader = getattr(provider, "get_daily", None)
            if callable(batch_loader):
                try:
                    frame = batch_loader(
                        list(_CORE_INDEX_SYMBOLS),
                        start_time=datetime.combine(target_date - timedelta(days=10), clock_time.min),
                        end_time=datetime.combine(target_date, clock_time.min),
                        asset_type="index",
                    )
                    if frame is not None and not frame.is_empty() and "date" in frame.columns:
                        latest = frame.get_column("date").drop_nulls().max()
                        if latest is not None and latest <= target_date:
                            # Keep the latest two trading dates.  The index
                            # cards need the prior close to calculate the
                            # displayed change; caching only the latest row
                            # silently turns a valid quote into "--".
                            dates = (
                                frame.get_column("date")
                                .drop_nulls()
                                .unique()
                                .sort(descending=True)
                                .head(2)
                                .to_list()
                            )
                            return frame.filter(pl.col("date").is_in(dates))
                except Exception as exc:
                    logger.warning("dashboard index batch unavailable: %s", type(exc).__name__)
        loader = getattr(provider, "get_latest_daily_snapshot", None)
        if not callable(loader):
            return pl.DataFrame()
        try:
            # TeaJoin supports an exact ``trade_date`` filter. Prefer it for
            # today's snapshot so a provider-side default row limit cannot
            # truncate a newly published trading day.
            frame = loader(
                asset_type=asset_type,
                as_of=datetime.combine(target_date, clock_time.min),
            )
        except TypeError:
            # Older custom providers exposed the stock-only method.  They
            # remain valid for stock data; index caching simply degrades to
            # an empty frame instead of breaking the dashboard refresh.
            try:
                frame = loader(asset_type=asset_type)
            except TypeError:
                if asset_type != "stock":
                    return pl.DataFrame()
                frame = loader()
        if frame is None or frame.is_empty() or "date" not in frame.columns:
            return pl.DataFrame()
        latest = frame.get_column("date").drop_nulls().max()
        if latest is None or latest > target_date:
            return pl.DataFrame()
        # A partial current-day daily row is never valid for dashboard
        # indicators. The target date already excludes it during a session,
        # but this guard also protects providers that ignore date filters.
        return frame.filter(pl.col("date") == latest).filter(pl.col("date") <= target_date)

    def _load_index_frame(
        provider_name: str,
        now_ms: float,
        target_date: date | None = None,
    ) -> pl.DataFrame:
        nonlocal last_index_frame, last_index_fetched_at_ms
        from app.data_providers import custom as custom_sources

        expected_date = target_date or resolve_market_as_of().daily_date
        align = (
            _complete_core_index_frame
            if expected_stock_symbols_loader is not None
            else _align_index_frame_to_date
        )
        if (
            not last_index_frame.is_empty()
            and last_index_fetched_at_ms is not None
            and now_ms - last_index_fetched_at_ms < daily_refresh_s * 1000
        ):
            cached = align(last_index_frame, expected_date)
            if not cached.is_empty():
                return cached
        if provider_name == "tickflow" or not custom_sources.provider_has_dataset(provider_name, "daily"):
            return align(last_index_frame, expected_date)
        try:
            index_provider = custom_sources.get_provider(provider_name)
            frame = _latest_daily(index_provider, "index")
            aligned = align(frame, expected_date)
            if not aligned.is_empty():
                last_index_frame = aligned
                last_index_fetched_at_ms = now_ms
        except Exception as exc:
            logger.warning("dashboard index snapshot unavailable: %s", type(exc).__name__)
        return align(last_index_frame, expected_date)

    def fetch() -> DashboardSnapshot:
        nonlocal last_daily
        from app.data_providers import custom as custom_sources
        from app.services import preferences
        from app.services.market_calendar import refresh_market_calendar

        refresh_market_calendar()
        market_asof = resolve_market_as_of()
        realtime_allowed = market_asof.session in {
            MarketSession.MORNING,
            MarketSession.AFTERNOON,
        }
        realtime_provider = preferences.get_realtime_data_provider()
        daily_provider = preferences.get_daily_data_provider()
        realtime_capable = (
            realtime_provider != "tickflow"
            and custom_sources.provider_has_dataset(realtime_provider, "realtime")
        )
        realtime_status = "provider_unavailable"
        if not realtime_allowed and realtime_capable:
            realtime_status = market_asof.session.value
        realtime_error: str | None = None

        if (
            realtime_allowed
            and realtime_capable
        ):
            try:
                provider = custom_sources.get_provider(realtime_provider)
                records = provider.get_realtime()
                date_verified = any(
                    key in row
                    for row in records
                    if isinstance(row, dict)
                    for key in ("date", "trade_date", "timestamp", "datetime")
                )
                frame = _normalise_realtime_frame(records)
                if "date" in frame.columns:
                    dates = frame.get_column("date").drop_nulls().unique().to_list()
                    if any(value != cn_today() for value in dates):
                        frame = pl.DataFrame()
                if not frame.is_empty():
                    index_frame = _load_index_frame(daily_provider, time.time() * 1000)
                    return DashboardSnapshot(
                        provider=realtime_provider,
                        kind=f"{realtime_provider}.realtime",
                        status="success",
                        snapshot_date=cn_today(),
                        frame=frame,
                        fetched_at_ms=time.time() * 1000,
                        error=None,
                        realtime_rows=frame.height,
                        index_frame=index_frame,
                        market_as_of={
                            "trade_date": cn_today().isoformat(),
                            "intraday_date": cn_today().isoformat(),
                            "cutoff_time": market_asof.cutoff_time,
                            "session": market_asof.session.value,
                            "is_partial": market_asof.is_partial,
                            "date_verified": date_verified,
                            "calendar_basis": trading_calendar_source(),
                            "observed_at": market_asof.observed_at.isoformat(),
                        },
                    )
                realtime_status = "empty"
            except Exception as exc:
                realtime_status = "error"
                realtime_error = type(exc).__name__
        elif realtime_provider != "tickflow" and not realtime_capable:
            realtime_status = "provider_unavailable"

        now_ms = time.time() * 1000
        daily_cache_s = daily_refresh_s
        if (
            last_daily is not None
            and market_asof.session in {MarketSession.POST_CLOSE, MarketSession.CLOSED}
            and last_daily.snapshot_date == market_asof.daily_date
            and last_daily.market_as_of.get("date_verified") is True
        ):
            # A verified completed candle does not change every 30 seconds.
            # Keep the normal short interval during live sessions, but avoid
            # downloading thousands of identical rows all evening/weekend.
            daily_cache_s = max(daily_refresh_s, _SETTLED_DAILY_REFRESH_S)
        if (
            last_daily is not None
            and last_daily.provider == daily_provider
            and last_daily.fetched_at_ms is not None
            and now_ms - last_daily.fetched_at_ms < daily_cache_s * 1000
        ):
            return replace(
                last_daily,
                status=realtime_status,
                error=realtime_error,
            )

        if daily_provider != "tickflow" and custom_sources.provider_has_dataset(daily_provider, "daily"):
            try:
                provider = custom_sources.get_provider(daily_provider)
                frame = _latest_daily(provider, "stock")
                if not frame.is_empty():
                    latest = frame.get_column("date").drop_nulls().max()
                    if latest is not None:
                        expected_symbols: set[str] | None = None
                        if expected_stock_symbols_loader is not None:
                            try:
                                expected_symbols = set(expected_stock_symbols_loader())
                            except Exception as exc:
                                logger.warning(
                                    "dashboard expected universe unavailable: %s",
                                    type(exc).__name__,
                                )
                        rejection = (
                            _daily_snapshot_rejection(frame, latest, expected_symbols)
                            if expected_stock_symbols_loader is not None
                            else None
                        )
                        if rejection is not None:
                            return DashboardSnapshot.empty(
                                daily_provider,
                                "invalid",
                                f"daily_quality:{rejection}",
                            )
                        now_ms = time.time() * 1000
                        _reset_daily_fallback_fail_count()
                        last_daily = DashboardSnapshot(
                            provider=daily_provider,
                            kind=f"{daily_provider}.daily",
                            status=realtime_status,
                            snapshot_date=latest,
                            frame=frame,
                            fetched_at_ms=now_ms,
                            error=realtime_error,
                            realtime_rows=0,
                            index_frame=_load_index_frame(daily_provider, now_ms, latest),
                            market_as_of={
                                "trade_date": latest.isoformat(),
                                "intraday_date": market_asof.intraday_date.isoformat()
                                if market_asof.intraday_date else None,
                                "cutoff_time": market_asof.cutoff_time,
                                "session": market_asof.session.value,
                                "is_partial": market_asof.is_partial,
                                "date_verified": True,
                                "calendar_basis": trading_calendar_source(),
                                "observed_at": market_asof.observed_at.isoformat(),
                            },
                        )
                        return last_daily
            except Exception as exc:
                global _daily_fallback_fail_count
                _daily_fallback_fail_count += 1
                # 不稳定源持续失败时降级为 debug 防刷屏, 每 50 次汇总一条 warning
                if _daily_fallback_fail_count <= 3 or _daily_fallback_fail_count % 50 == 0:
                    logger.warning("dashboard daily fallback unavailable(连续%d次): %s", _daily_fallback_fail_count, type(exc).__name__)
                else:
                    logger.debug("dashboard daily fallback unavailable(连续%d次): %s", _daily_fallback_fail_count, type(exc).__name__)
                realtime_error = realtime_error or type(exc).__name__

        return DashboardSnapshot.empty(daily_provider, realtime_status, realtime_error)

    return fetch


def make_sina_intraday_snapshot_fetcher(
    symbol_loader: Callable[[], list[str]],
    index_symbol_loader: Callable[[], list[str]],
    repo,
    *,
    interval_s: float = 30.0,
) -> Callable[[], DashboardSnapshot]:
    """Build the dashboard's keyless intraday snapshot fetcher.

    Sina is used only as an in-memory dashboard snapshot during an A-share
    trading session.  It is deliberately not written to the daily parquet
    partitions before the close boundary; the existing post-close pipeline
    remains the only writer of the completed daily candle.  This lets a
    no-TickFlow-key deployment show today's breadth from the open without
    turning a partial candle into historical data.
    """
    last_date: date | None = None
    previous_close: dict[str, float] = {}
    labels: pl.DataFrame | None = None
    index_previous_close: dict[str, float] = {}

    def _load_previous_close(trade_date: date, asset_type: str, symbols: list[str]) -> dict[str, float]:
        if asset_type == "stock":
            try:
                latest, latest_date = repo.get_enriched_latest()
                if latest_date is not None and latest_date < trade_date and not latest.is_empty():
                    close_col = "raw_close" if "raw_close" in latest.columns else "close"
                    if "symbol" in latest.columns and close_col in latest.columns:
                        return {
                            str(symbol): float(close)
                            for symbol, close in latest.select(["symbol", close_col]).iter_rows()
                            if symbol and close is not None and float(close) > 0
                        }
            except Exception as exc:  # noqa: BLE001
                logger.debug("sina previous stock close unavailable: %s", type(exc).__name__)

        if not symbols:
            return {}
        table = "kline_index_daily" if asset_type == "index" else "kline_daily"
        placeholders = ", ".join("?" for _ in symbols)
        try:
            rows = repo.execute_all(
                f"""
                WITH ranked AS (
                    SELECT symbol, close,
                           row_number() OVER (PARTITION BY symbol ORDER BY date DESC) AS rn
                    FROM {table}
                    WHERE date < ? AND symbol IN ({placeholders})
                )
                SELECT symbol, close FROM ranked WHERE rn = 1
                """,
                [trade_date, *symbols],
            )
            return {
                str(symbol): float(close)
                for symbol, close in rows
                if symbol and close is not None and float(close) > 0
            }
        except Exception as exc:  # noqa: BLE001
            logger.debug("sina previous %s close unavailable: %s", asset_type, type(exc).__name__)
            return {}

    def _normalise_date(frame: pl.DataFrame, trade_date: date) -> pl.DataFrame:
        if frame.is_empty() or "date" not in frame.columns:
            return pl.DataFrame()
        try:
            frame = frame.with_columns(pl.col("date").cast(pl.Date, strict=False))
        except Exception:
            return pl.DataFrame()
        return frame.filter(pl.col("date") == trade_date)

    def fetch() -> DashboardSnapshot:
        nonlocal last_date, previous_close, labels, index_previous_close
        market_asof = resolve_market_as_of()
        trade_date = market_asof.intraday_date
        now_ms = time.time() * 1000
        if market_asof.session not in {MarketSession.MORNING, MarketSession.AFTERNOON}:
            # Sina is only a realtime fallback; during lunch, pre-open and
            # after close the dashboard must not retain or refresh a partial
            # quote as if the exchange were trading.
            return DashboardSnapshot.empty("sina", market_asof.session.value)
        if trade_date is None:
            return DashboardSnapshot.empty("sina", market_asof.session.value)

        try:
            symbols = sorted(set(symbol_loader()))
        except Exception as exc:  # noqa: BLE001
            return DashboardSnapshot.empty("sina", "error", type(exc).__name__)
        if not symbols:
            return DashboardSnapshot.empty("sina", "empty")

        if last_date != trade_date:
            last_date = trade_date
            previous_close = _load_previous_close(trade_date, "stock", symbols)
            index_previous_close = {}
            labels = None
        try:
            from app.services import sina_snapshot

            frame = _normalise_date(sina_snapshot.fetch_market_spot(symbols), trade_date)
            if frame.is_empty():
                return DashboardSnapshot.empty("sina", "empty")

            if labels is None:
                try:
                    instruments = repo.get_instruments()
                    if instruments is not None and not instruments.is_empty() and "symbol" in instruments.columns:
                        columns = [c for c in ("symbol", "name", "float_shares") if c in instruments.columns]
                        labels = instruments.select(columns).unique(subset=["symbol"], keep="last")
                except Exception as exc:  # noqa: BLE001
                    logger.debug("sina instrument labels unavailable: %s", type(exc).__name__)
                    labels = pl.DataFrame()
            if labels is not None and not labels.is_empty():
                right = labels.rename({"name": "_instrument_name"}) if "name" in labels.columns else labels
                frame = frame.join(right, on="symbol", how="left")
                if "_instrument_name" in frame.columns:
                    if "name" in frame.columns:
                        frame = frame.with_columns(
                            pl.when(
                                pl.col("name").is_null()
                                | (pl.col("name").cast(pl.Utf8).str.strip_chars() == "")
                            )
                            .then(pl.col("_instrument_name"))
                            .otherwise(pl.col("name"))
                            .alias("name")
                        ).drop("_instrument_name")
                    else:
                        frame = frame.rename({"_instrument_name": "name"})

            # 昨收优先取新浪快照字段(除权除息日为交易所调整后的基准价, 涨跌幅
            # 与涨跌停价都以它为准), 缺失时回落本地昨日 raw_close。停牌行
            # (close=0)不得派生涨跌幅, 由下游停牌过滤(volume=0 且 change_pct=0)
            # 剔除, 否则会混入下跌统计。
            prev = pl.DataFrame({
                "symbol": list(previous_close),
                "_repo_prev_close": list(previous_close.values()),
            })
            if not prev.is_empty():
                frame = frame.join(prev, on="symbol", how="left")
                if "prev_close" in frame.columns:
                    frame = frame.with_columns(
                        pl.when(pl.col("prev_close").cast(pl.Float64, strict=False) > 0)
                        .then(pl.col("prev_close"))
                        .otherwise(pl.col("_repo_prev_close"))
                        .alias("prev_close")
                    ).drop("_repo_prev_close")
                else:
                    frame = frame.rename({"_repo_prev_close": "prev_close"})
            if "prev_close" in frame.columns:
                frame = frame.with_columns(
                    pl.when(
                        (pl.col("prev_close") > 0)
                        & (pl.col("close") > 0)
                    )
                    .then((pl.col("close") - pl.col("prev_close")) / pl.col("prev_close"))
                    .otherwise(None)
                    .alias("change_pct")
                )

            index_symbols = sorted(set(index_symbol_loader()))
            index_frame = _normalise_date(
                sina_snapshot.fetch_market_spot(index_symbols, asset_type="index"),
                trade_date,
            ) if index_symbols else pl.DataFrame()
            if not index_frame.is_empty():
                if not index_previous_close:
                    index_previous_close = _load_previous_close(trade_date, "index", index_symbols)
                idx_prev = pl.DataFrame({
                    "symbol": list(index_previous_close),
                    "_repo_prev_close": list(index_previous_close.values()),
                })
                if not idx_prev.is_empty():
                    index_frame = index_frame.join(idx_prev, on="symbol", how="left")
                    if "prev_close" in index_frame.columns:
                        index_frame = index_frame.with_columns(
                            pl.when(pl.col("prev_close").cast(pl.Float64, strict=False) > 0)
                            .then(pl.col("prev_close"))
                            .otherwise(pl.col("_repo_prev_close"))
                            .alias("prev_close")
                        ).drop("_repo_prev_close")
                    else:
                        index_frame = index_frame.rename({"_repo_prev_close": "prev_close"})

            return DashboardSnapshot(
                provider="sina",
                kind="sina.realtime",
                status="success",
                snapshot_date=trade_date,
                frame=frame,
                fetched_at_ms=now_ms,
                error=None,
                realtime_rows=frame.height,
                index_frame=index_frame,
                market_as_of={
                    "trade_date": trade_date.isoformat(),
                    "intraday_date": trade_date.isoformat(),
                    "cutoff_time": market_asof.cutoff_time,
                    "session": market_asof.session.value,
                    "is_partial": True,
                    "observed_at": market_asof.observed_at.isoformat(),
                },
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("sina dashboard snapshot failed: %s", type(exc).__name__)
            return DashboardSnapshot.empty("sina", "error", type(exc).__name__)

    return fetch
