from __future__ import annotations

import json
from datetime import date
from types import SimpleNamespace

import httpx
import polars as pl
import pytest

from app.data_providers import custom
from app.maintenance import rebuild_share_history as runner
from app.services import financial_sync, preferences
from app.tickflow.capabilities import CapabilitySet


def test_share_history_fetch_propagates_transport_failure(monkeypatch, tmp_path):
    error = httpx.ReadTimeout("upstream timed out")

    class Provider:
        def get_financials(self, *_args, **_kwargs):
            raise error

    monkeypatch.setattr(financial_sync, "_financial_is_custom", lambda: True)
    monkeypatch.setattr(preferences, "get_financial_provider", lambda: "test")
    monkeypatch.setattr(custom, "get_provider", lambda _: Provider())
    with pytest.raises(httpx.ReadTimeout):
        financial_sync._fetch_table(
            "shares", ["000402.SZ"], CapabilitySet(), latest_only=False,
            raise_on_error=True,
        )


def test_rebuild_transport_failure_preserves_parquet_and_checkpoint(monkeypatch, tmp_path):
    inst = tmp_path / "instruments" / "instruments.parquet"
    inst.parent.mkdir()
    pl.DataFrame({"symbol": ["000001.SZ", "000402.SZ"]}).write_parquet(inst)
    daily = tmp_path / "kline_daily" / "date=2025-09-10" / "part.parquet"
    daily.parent.mkdir(parents=True)
    pl.DataFrame({"symbol": ["000402.SZ"], "date": [date(2025, 9, 10)]}).write_parquet(daily)
    shares = tmp_path / "financials" / "shares" / "part.parquet"
    shares.parent.mkdir(parents=True)
    pl.DataFrame({
        "symbol": ["000001.SZ"], "period_end": ["20250910"], "float_shares": [10.0],
    }).write_parquet(shares)
    state = shares.with_name("rebuild-state.json")
    state.write_text(json.dumps({
        "completed_symbols": ["000001.SZ"], "complete": False, "coverage_start": "2025-09-10",
    }), encoding="utf-8")
    before = (shares.read_bytes(), state.read_bytes())

    def fail(*_args, **_kwargs):
        raise httpx.ReadTimeout("upstream timed out")

    monkeypatch.setattr(financial_sync, "_fetch_table", fail)
    with pytest.raises(httpx.ReadTimeout):
        financial_sync.rebuild_share_history_batch(tmp_path, CapabilitySet(), batch_size=1)
    assert (shares.read_bytes(), state.read_bytes()) == before


def _setup_runner(monkeypatch):
    monkeypatch.setattr(runner, "_arguments", lambda: SimpleNamespace(
        batch_size=1, until_complete=True,
    ))
    monkeypatch.setattr(custom, "load_all", lambda: None)


@pytest.mark.parametrize("error", [
    httpx.ReadTimeout("upstream timed out"),
    httpx.HTTPStatusError(
        "unavailable", request=httpx.Request("POST", "https://example.test"),
        response=httpx.Response(503),
    ),
    httpx.HTTPStatusError(
        "bad gateway", request=httpx.Request("POST", "https://example.test"),
        response=httpx.Response(502),
    ),
    httpx.HTTPStatusError(
        "rate limited", request=httpx.Request("POST", "https://example.test"),
        response=httpx.Response(429),
    ),
])
def test_runner_retries_transient_failure_without_skipping_batch(monkeypatch, capsys, error):
    _setup_runner(monkeypatch)
    attempts = []

    def repair(*_args, **_kwargs):
        attempts.append(1)
        if len(attempts) == 1:
            raise error
        return {"complete": True, "remaining_symbols": 0, "processed_symbols": 1, "rows": 2}

    monkeypatch.setattr(runner, "rebuild_share_history_batch", repair)
    monkeypatch.setattr("time.sleep", lambda _: None)
    assert runner.main() == 0
    assert len(attempts) == 2
    assert '"complete": true' in capsys.readouterr().out


@pytest.mark.parametrize("error", [
    RuntimeError("share history batch returned no rows; checkpoint unchanged"),
    ValueError("invalid configuration"),
    httpx.HTTPStatusError(
        "unauthorized", request=httpx.Request("POST", "https://example.test"),
        response=httpx.Response(401),
    ),
    httpx.HTTPStatusError(
        "bad parameters", request=httpx.Request("POST", "https://example.test"),
        response=httpx.Response(400),
    ),
    httpx.HTTPStatusError(
        "forbidden", request=httpx.Request("POST", "https://example.test"),
        response=httpx.Response(403),
    ),
])
def test_runner_does_not_retry_deterministic_failure(monkeypatch, capsys, error):
    _setup_runner(monkeypatch)
    attempts = []

    def repair(*_args, **_kwargs):
        attempts.append(1)
        raise error

    monkeypatch.setattr(runner, "rebuild_share_history_batch", repair)
    assert runner.main() == 1
    assert len(attempts) == 1
    assert '"status": "error"' in capsys.readouterr().err


def test_runner_transient_retries_are_bounded_and_redacted(monkeypatch, capsys):
    _setup_runner(monkeypatch)
    attempts = []

    def repair(*_args, **_kwargs):
        attempts.append(1)
        raise httpx.ReadTimeout("credential=must-not-log")

    monkeypatch.setattr(runner, "rebuild_share_history_batch", repair)
    monkeypatch.setattr("time.sleep", lambda _: None)
    assert runner.main() == 1
    assert len(attempts) == 4
    assert "must-not-log" not in capsys.readouterr().err


def test_runner_resets_retry_budget_only_after_successful_batch(monkeypatch):
    _setup_runner(monkeypatch)
    error = httpx.ReadTimeout("upstream timed out")
    first = {"complete": False, "remaining_symbols": 1, "processed_symbols": 1, "rows": 2}
    second = {"complete": True, "remaining_symbols": 0, "processed_symbols": 1, "rows": 4}
    results = iter([error, error, error, first, error, error, error, second])
    delays = []

    def repair(*_args, **_kwargs):
        result = next(results)
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(runner, "rebuild_share_history_batch", repair)
    monkeypatch.setattr("time.sleep", delays.append)
    assert runner.main() == 0
    assert delays == [5, 10, 20, 5, 10, 20]
