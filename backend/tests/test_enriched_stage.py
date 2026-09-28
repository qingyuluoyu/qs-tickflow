from __future__ import annotations

import json
from datetime import date

import polars as pl
import pytest

from app.maintenance import rebuild_enriched_stage as maintenance


def _inputs(root, *, complete=True, completed=None):
    symbols = ["000001.SZ", "600000.SH"]
    daily = root / "kline_daily/date=2024-01-02/part.parquet"
    daily.parent.mkdir(parents=True)
    pl.DataFrame({
        "symbol": symbols, "date": [date(2024, 1, 2)] * 2,
        "open": [10.0, 20.0], "high": [11.0, 21.0], "low": [9.0, 19.0],
        "close": [10.5, 20.5], "volume": [100.0, 200.0], "amount": [1e5, 4e5],
    }).write_parquet(daily)
    inst = root / "instruments/instruments.parquet"
    inst.parent.mkdir()
    pl.DataFrame({"symbol": symbols, "float_shares": [9e8, 9e8]}).write_parquet(inst)
    shares = root / "financials/shares/part.parquet"
    shares.parent.mkdir(parents=True)
    pl.DataFrame({
        "symbol": symbols, "period_end": ["20240101"] * 2,
        "announce_date": ["20240101"] * 2, "float_shares": [1e6, 4e6],
    }).write_parquet(shares)
    (shares.parent / "rebuild-state.json").write_text(json.dumps({
        "complete": complete, "completed_symbols": symbols if completed is None else completed,
        "coverage_start": "2024-01-02",
    }))
    live = root / "kline_daily_enriched/date=2024-01-02/part.parquet"
    live.parent.mkdir(parents=True)
    pl.DataFrame({"symbol": symbols, "date": [date(2024, 1, 2)] * 2, "close": [1.0, 1.0]}).write_parquet(live)
    return live


@pytest.mark.parametrize("complete,completed", [(False, None), (True, ["000001.SZ"])])
def test_stage_refuses_incomplete_checkpoint_without_live_writes(tmp_path, complete, completed):
    live = _inputs(tmp_path, complete=complete, completed=completed)
    before = live.read_bytes()
    with pytest.raises(RuntimeError, match="share repair incomplete"):
        maintenance.rebuild_enriched_stage(tmp_path, batch_size=1)
    assert live.read_bytes() == before
    assert not list((tmp_path / "maintenance").glob("enriched-stage-*"))


def test_stage_runs_real_pipeline_in_batches_and_preserves_live(tmp_path):
    live = _inputs(tmp_path)
    before = live.read_bytes()
    report = maintenance.rebuild_enriched_stage(tmp_path, batch_size=1)
    assert report["status"] == "validated"
    assert report["batches"] == 2
    assert report["rows"] == 2
    assert report["missing_turnover_rows"] == 0
    stage = tmp_path / report["stage"]
    result = pl.read_parquet(stage / "kline_daily_enriched/date=2024-01-02/part.parquet")
    assert result.sort("symbol")["turnover_rate"].to_list() == [1.0, 0.5]
    assert live.read_bytes() == before
    manifest = json.loads((stage / "manifest.json").read_text())
    assert manifest["inputs"]["financials/shares/part.parquet"]
    assert manifest["live_enriched"]["kline_daily_enriched/date=2024-01-02/part.parquet"]
    assert manifest["outputs"]["kline_daily_enriched/date=2024-01-02/part.parquet"]


def test_stage_preserves_genuinely_unavailable_history_as_null(tmp_path):
    _inputs(tmp_path)
    shares = tmp_path / "financials/shares/part.parquet"
    frame = pl.read_parquet(shares).with_columns(pl.lit("20240103").alias("announce_date"))
    frame.write_parquet(shares)
    report = maintenance.rebuild_enriched_stage(tmp_path)
    assert report["status"] == "validated"
    assert report["missing_turnover_rows"] == 2
    assert report["ready_for_publication"] is False


@pytest.mark.parametrize("column,value", [("turnover_rate", 99.0), ("volume", 99.0), ("raw_close", 99.0), ("close", 99.0)])
def test_validation_rejects_changed_financial_values(tmp_path, column, value):
    _inputs(tmp_path)
    report = maintenance.rebuild_enriched_stage(tmp_path)
    stage = tmp_path / report["stage"]
    out = stage / "kline_daily_enriched/date=2024-01-02/part.parquet"
    pl.read_parquet(out).with_columns(pl.lit(value).alias(column)).write_parquet(out)
    with pytest.raises(RuntimeError, match="staged financial values"):
        maintenance.validate_stage(stage)


def test_validation_rejects_duplicate_or_missing_keys(tmp_path):
    _inputs(tmp_path)
    report = maintenance.rebuild_enriched_stage(tmp_path)
    stage = tmp_path / report["stage"]
    out = stage / "kline_daily_enriched/date=2024-01-02/part.parquet"
    frame = pl.read_parquet(out)
    pl.concat([frame.head(1), frame.head(1)]).write_parquet(out)
    with pytest.raises(RuntimeError, match="staged keys"):
        maintenance.validate_stage(stage)


def test_input_fingerprint_detects_changes(tmp_path):
    _inputs(tmp_path)
    report = maintenance.rebuild_enriched_stage(tmp_path)
    stage = tmp_path / report["stage"]
    manifest = json.loads((stage / "manifest.json").read_text())
    assert maintenance.inputs_unchanged(tmp_path, manifest)
    shares = tmp_path / "financials/shares/part.parquet"
    pl.read_parquet(shares).with_columns(pl.lit(8e6).alias("float_shares")).write_parquet(shares)
    assert not maintenance.inputs_unchanged(tmp_path, manifest)


def test_stage_rejects_stale_coverage_and_invalid_batch(tmp_path):
    _inputs(tmp_path)
    state = tmp_path / "financials/shares/rebuild-state.json"
    payload = json.loads(state.read_text())
    payload["coverage_start"] = "2024-01-03"
    state.write_text(json.dumps(payload))
    with pytest.raises(RuntimeError, match="share repair coverage"):
        maintenance.rebuild_enriched_stage(tmp_path)
    with pytest.raises(ValueError, match="batch_size"):
        maintenance.rebuild_enriched_stage(tmp_path, batch_size=0)


@pytest.mark.parametrize("column,value", [("ex_factor", 0.0), ("forward_factor", 1.0)])
def test_stage_rejects_invalid_adjustment_factor(tmp_path, column, value):
    _inputs(tmp_path)
    factors = tmp_path / "adj_factor/all.parquet"
    factors.parent.mkdir()
    pl.DataFrame({"symbol": ["000001.SZ"], "trade_date": [date(2024, 1, 2)], column: [value]}).write_parquet(factors)
    with pytest.raises(RuntimeError, match="adjustment factor"):
        maintenance.rebuild_enriched_stage(tmp_path)


def test_stage_aborts_if_source_changes_during_snapshot(tmp_path, monkeypatch):
    live = _inputs(tmp_path)
    before = live.read_bytes()
    original_copy = maintenance.shutil.copy2

    def racing_copy(source, target):
        result = original_copy(source, target)
        if source.name == "rebuild-state.json":
            source.write_text(source.read_text() + " ")
        return result

    monkeypatch.setattr(maintenance.shutil, "copy2", racing_copy)
    with pytest.raises(RuntimeError, match="changed during snapshot"):
        maintenance.rebuild_enriched_stage(tmp_path)
    assert live.read_bytes() == before
    manifest = next((tmp_path / "maintenance").glob("enriched-stage-*/manifest.json"))
    assert json.loads(manifest.read_text())["status"] == "failed"


def test_stage_computes_raw_only_security_from_historical_shares(tmp_path):
    _inputs(tmp_path)
    instruments = tmp_path / "instruments/instruments.parquet"
    pl.read_parquet(instruments).filter(pl.col("symbol") == "600000.SH").write_parquet(instruments)
    report = maintenance.rebuild_enriched_stage(tmp_path, batch_size=1)
    assert report["missing_turnover_rows"] == 0
    assert report["rows"] == 2


def test_stage_rejects_unparseable_factor_date(tmp_path):
    _inputs(tmp_path)
    factors = tmp_path / "adj_factor/all.parquet"
    factors.parent.mkdir()
    pl.DataFrame({"symbol": ["000001.SZ"], "trade_date": ["bad-date"], "ex_factor": [2.0]}).write_parquet(factors)
    with pytest.raises(RuntimeError, match="adjustment factor"):
        maintenance.rebuild_enriched_stage(tmp_path)


def test_stage_rechecks_completion_after_snapshot(tmp_path, monkeypatch):
    _inputs(tmp_path)
    fingerprint = maintenance._fingerprints
    changed = False

    def racing_fingerprint(root, files):
        nonlocal changed
        if not changed:
            changed = True
            state = root / "financials/shares/rebuild-state.json"
            payload = json.loads(state.read_text())
            payload["complete"] = False
            state.write_text(json.dumps(payload))
        return fingerprint(root, files)

    monkeypatch.setattr(maintenance, "_fingerprints", racing_fingerprint)
    with pytest.raises(RuntimeError, match="share repair incomplete"):
        maintenance.rebuild_enriched_stage(tmp_path)


def test_missing_instrument_output_is_independent_of_batch_neighbors(tmp_path):
    _inputs(tmp_path)
    instruments = tmp_path / "instruments/instruments.parquet"
    pl.read_parquet(instruments).filter(pl.col("symbol") == "600000.SH").write_parquet(instruments)
    reports = [maintenance.rebuild_enriched_stage(tmp_path, batch_size=size) for size in (1, 2)]
    frames = [pl.read_parquet(tmp_path / report["stage"] / "kline_daily_enriched/date=2024-01-02/part.parquet").sort("symbol") for report in reports]
    assert frames[0].equals(frames[1])
    unknown = frames[0].filter(pl.col("symbol") == "000001.SZ")
    assert unknown["turnover_rate"].to_list() == [1.0]
    assert unknown["consecutive_limit_ups"].to_list() == [None]
    assert unknown["consecutive_limit_downs"].to_list() == [None]
