import asyncio
import threading
import time
from datetime import datetime, timedelta, timezone

import pytest

from app.services import financial_sync


def test_recent_metrics_sync_is_not_due_after_restart():
    scheduler = financial_sync.FinancialScheduler()
    now = datetime(2026, 8, 24, 15, 0, tzinfo=timezone.utc)
    scheduler._schedule_interval_days = 7
    scheduler._last_sync["metrics"] = (now - timedelta(days=1)).isoformat()

    assert not scheduler._metrics_sync_due(now)


def test_missing_or_expired_metrics_sync_is_due():
    scheduler = financial_sync.FinancialScheduler()
    now = datetime(2026, 8, 24, 15, 0, tzinfo=timezone.utc)
    scheduler._schedule_interval_days = 7

    assert scheduler._metrics_sync_due(now)
    scheduler._last_sync["metrics"] = (now - timedelta(days=8)).isoformat()
    assert scheduler._metrics_sync_due(now)


@pytest.mark.asyncio
async def test_scheduled_financial_sync_does_not_block_http_event_loop(monkeypatch, tmp_path):
    """A slow provider call must not freeze authentication or other HTTP work."""
    scheduler = financial_sync.FinancialScheduler()
    scheduler._running = True
    scheduler._data_dir = tmp_path
    scheduler._capset = object()

    sync_started = threading.Event()
    release_sync = threading.Event()

    def slow_sync(_data_dir, _capset):
        sync_started.set()
        release_sync.wait(timeout=1)
        scheduler._running = False
        return 1

    real_sleep = asyncio.sleep

    async def skip_initial_delay(seconds):
        await real_sleep(0 if seconds == 60 else seconds)

    monkeypatch.setattr(financial_sync, "sync_metrics", slow_sync)
    monkeypatch.setattr(financial_sync.asyncio, "sleep", skip_initial_delay)

    # Release the fake upstream request even when the old implementation
    # blocks the event loop, so the regression test cannot hang indefinitely.
    release_timer = threading.Timer(0.25, release_sync.set)
    release_timer.start()
    task = asyncio.create_task(scheduler._run_loop())
    try:
        started_at = time.perf_counter()
        await asyncio.sleep(0.01)
        elapsed = time.perf_counter() - started_at

        assert sync_started.is_set()
        assert elapsed < 0.1
        await asyncio.wait_for(task, timeout=1)
    finally:
        release_sync.set()
        release_timer.cancel()
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
