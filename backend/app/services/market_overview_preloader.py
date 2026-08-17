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
from dataclasses import dataclass, replace
from datetime import date

import polars as pl

from app.market_time import cn_today

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DashboardSnapshot:
    provider: str
    kind: str
    status: str
    snapshot_date: date | None
    frame: pl.DataFrame
    fetched_at_ms: float | None
    error: str | None

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
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def _copy(self, snapshot: DashboardSnapshot | None) -> DashboardSnapshot | None:
        if snapshot is None:
            return None
        return replace(snapshot, frame=snapshot.frame.clone())

    def snapshot(self) -> DashboardSnapshot | None:
        with self._lock:
            return self._copy(self._snapshot)

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
                    self._snapshot = candidate
                elif previous is not None and not previous.frame.is_empty():
                    # Keep prices/rankings from the last valid snapshot, but
                    # replace status so the UI exposes the current failure.
                    self._snapshot = replace(
                        previous,
                        status=candidate.status,
                        fetched_at_ms=(
                            candidate.fetched_at_ms
                            if candidate.fetched_at_ms is not None
                            else previous.fetched_at_ms
                        ),
                        error=candidate.error,
                    )
                else:
                    self._snapshot = candidate
                return self._copy(self._snapshot)
        except Exception as exc:
            logger.warning("dashboard snapshot preload failed: %s", type(exc).__name__)
            with self._lock:
                previous = self._snapshot
                if previous is not None and not previous.frame.is_empty():
                    self._snapshot = replace(
                        previous,
                        status="error",
                        fetched_at_ms=time.time() * 1000,
                        error=type(exc).__name__,
                    )
                else:
                    self._snapshot = DashboardSnapshot.empty("unknown", "error", type(exc).__name__)
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


def _normalise_realtime_frame(records: list[dict]) -> pl.DataFrame:
    if not records:
        return pl.DataFrame()
    frame = pl.DataFrame(records)
    if "symbol" not in frame.columns:
        return pl.DataFrame()
    if "close" not in frame.columns and "last_price" in frame.columns:
        frame = frame.with_columns(pl.col("last_price").alias("close"))
    if "date" not in frame.columns:
        frame = frame.with_columns(pl.lit(cn_today()).cast(pl.Date).alias("date"))
    numeric = [
        "close", "last_price", "prev_close", "open", "high", "low", "volume",
        "amount", "change_pct", "change_amount", "amplitude", "turnover_rate",
    ]
    present = [column for column in numeric if column in frame.columns]
    if present:
        frame = frame.with_columns(
            [pl.col(column).cast(pl.Float64, strict=False).alias(column) for column in present]
        )
    # The provider contract stores realtime rates as decimals (0.0315 =
    # 3.15%), while the dashboard/enriched response exposes percentages.
    # Convert once at this boundary so activity cards use the same unit for
    # realtime and daily-derived snapshots.
    if "turnover_rate" in frame.columns:
        frame = frame.with_columns(
            (pl.col("turnover_rate") * 100.0).alias("turnover_rate")
        )
    return frame


def make_dashboard_snapshot_fetcher(*, daily_refresh_s: float = 300.0) -> Callable[[], DashboardSnapshot]:
    """Build the production TeaJoin snapshot fetcher.

    Realtime is attempted every preload cycle. The daily fallback is throttled
    independently because it is a slower request and cannot become today's
    intraday data merely because it returned successfully.
    """
    last_daily: DashboardSnapshot | None = None

    def fetch() -> DashboardSnapshot:
        nonlocal last_daily
        from app.data_providers import custom as custom_sources
        from app.services import preferences

        realtime_provider = preferences.get_realtime_data_provider()
        daily_provider = preferences.get_daily_data_provider()
        realtime_status = "provider_unavailable"
        realtime_error: str | None = None

        if realtime_provider != "tickflow" and custom_sources.provider_has_dataset(realtime_provider, "realtime"):
            try:
                provider = custom_sources.get_provider(realtime_provider)
                frame = _normalise_realtime_frame(provider.get_realtime())
                if not frame.is_empty():
                    return DashboardSnapshot(
                        provider=realtime_provider,
                        kind=f"{realtime_provider}.realtime",
                        status="success",
                        snapshot_date=cn_today(),
                        frame=frame,
                        fetched_at_ms=time.time() * 1000,
                        error=None,
                    )
                realtime_status = "empty"
            except Exception as exc:
                realtime_status = "error"
                realtime_error = type(exc).__name__
        elif realtime_provider != "tickflow":
            realtime_status = "provider_unavailable"

        now_ms = time.time() * 1000
        if (
            last_daily is not None
            and last_daily.provider == daily_provider
            and last_daily.fetched_at_ms is not None
            and now_ms - last_daily.fetched_at_ms < daily_refresh_s * 1000
        ):
            return replace(
                last_daily,
                status=realtime_status,
                error=realtime_error,
            )

        if daily_provider != "tickflow" and custom_sources.provider_has_dataset(daily_provider, "daily"):
            try:
                provider = custom_sources.get_provider(daily_provider)
                frame = provider.get_latest_daily_snapshot()
                if frame is not None and not frame.is_empty() and "date" in frame.columns:
                    latest = frame.get_column("date").drop_nulls().max()
                    if latest is not None and latest <= cn_today():
                        last_daily = DashboardSnapshot(
                            provider=daily_provider,
                            kind=f"{daily_provider}.daily",
                            status=realtime_status,
                            snapshot_date=latest,
                            frame=frame,
                            fetched_at_ms=now_ms,
                            error=realtime_error,
                        )
                        return last_daily
            except Exception as exc:
                logger.warning("dashboard daily fallback unavailable: %s", type(exc).__name__)
                realtime_error = realtime_error or type(exc).__name__

        return DashboardSnapshot.empty(daily_provider, realtime_status, realtime_error)

    return fetch
