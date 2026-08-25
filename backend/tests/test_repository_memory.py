from __future__ import annotations

import threading
from datetime import date, timedelta

import polars as pl

from app.tickflow import repository


def test_linux_temporary_memory_release_runs_gc_and_malloc_trim(monkeypatch):
    calls: list[object] = []

    class LibC:
        @staticmethod
        def malloc_trim(pad):
            calls.append(("trim", pad))
            return 1

    monkeypatch.setattr(repository.gc, "collect", lambda: calls.append("gc"))
    monkeypatch.setattr(repository.sys, "platform", "linux")
    monkeypatch.setattr(repository.ctypes, "CDLL", lambda _name: LibC())

    repository._release_temporary_memory()

    assert calls == ["gc", ("trim", 0)]


def test_enriched_warmup_releases_temporaries_after_refresh(monkeypatch):
    calls: list[str] = []
    repo = object.__new__(repository.KlineRepository)
    repo._warmup_lock = threading.Lock()
    repo._enriched_warming = False
    repo._warmup_thread = None
    repo._on_warmup_done = None
    repo._on_refresh_done = None
    repo._refresh_enriched = lambda: calls.append("refresh")
    repo._notify_refresh_done = lambda: calls.append("notify")
    monkeypatch.setattr(
        repository,
        "_release_temporary_memory",
        lambda: calls.append("release"),
    )

    repo._start_enriched_warmup()
    repo._warmup_thread.join(timeout=2)

    assert calls == ["refresh", "release", "notify"]


def test_history_cache_projection_keeps_financial_fields_without_repeated_metadata():
    df = pl.DataFrame(
        {
            "symbol": ["000001.SZ"],
            "date": [date(2026, 8, 24)],
            "close": [10.0],
            "amount": [1000.0],
            "change_pct": [0.01],
            "ma20": [9.8],
            "signal_limit_up": [False],
            "name": ["平安银行"],
            "total_shares": [1_000_000.0],
            "signal_ma_golden_5_20": [False],
        }
    )

    projected = repository._project_history_cache(df)

    assert projected.columns == [
        "symbol",
        "date",
        "close",
        "amount",
        "change_pct",
        "ma20",
        "signal_limit_up",
        "signal_ma_golden_5_20",
    ]


def test_history_range_returns_cache_miss_when_requested_field_is_not_projected():
    repo = object.__new__(repository.KlineRepository)
    start = date(2026, 8, 20)
    repo._enriched_history_cache = pl.DataFrame(
        {
            "symbol": ["000001.SZ", "000001.SZ", "000001.SZ"],
            "date": [start, start + timedelta(days=1), start + timedelta(days=2)],
            "change_pct": [0.01, 0.02, -0.01],
        }
    )

    assert repo.get_enriched_range(start, start + timedelta(days=2), columns=["rsi_14"]) is None
    assert repo.get_enriched_range(start, start + timedelta(days=2)) is None
