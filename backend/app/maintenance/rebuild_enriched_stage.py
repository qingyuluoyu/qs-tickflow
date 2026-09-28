"""Build and validate an isolated enriched snapshot; never publish live data."""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import tempfile
from datetime import date
from pathlib import Path

import polars as pl

from app.config import settings
from app.indicators.pipeline import _apply_adj_factor, filter_halt_days, run_pipeline
from app.market_time import cn_today
from app.parquet import scan_daily_parquet, scan_enriched_parquet, scan_parquet_compat
from app.services.financial_sync import (
    _daily_share_coverage_start,
    _read_share_history_rebuild_state,
    share_history_rebuild_symbols,
)
from app.share_capital import apply_historical_float_shares


def _input_files(root: Path) -> list[Path]:
    files = [*sorted((root / "kline_daily").rglob("*.parquet")),
             *sorted((root / "instruments").rglob("*.parquet")),
             root / "financials/shares/part.parquet",
             root / "financials/shares/rebuild-state.json"]
    factors = root / "adj_factor/all.parquet"
    if factors.exists():
        files.append(factors)
    for path in files:
        if not path.is_file() or not path.resolve().is_relative_to(root.resolve()):
            raise RuntimeError("missing or unsafe enriched input")
    return files


def _fingerprints(root: Path, files: list[Path]) -> dict[str, str]:
    result = {}
    for path in files:
        with path.open("rb") as stream:
            result[path.relative_to(root).as_posix()] = hashlib.file_digest(stream, "sha256").hexdigest()
    return result


def inputs_unchanged(root: Path, manifest: dict) -> bool:
    """Publication prerequisite; compare the complete live input set and content."""
    return _fingerprints(root, _input_files(root)) == manifest["inputs"]


def _validated_factors(stage: Path) -> pl.DataFrame:
    # The pipeline tolerates an unreadable file by running unadjusted. Reject
    # that silent financial downgrade during a maintenance rebuild.
    factor_path = stage / "adj_factor/all.parquet"
    if factor_path.exists():
        factors = pl.read_parquet(factor_path)
        if not {"symbol", "trade_date", "ex_factor"} <= set(factors.columns):
            raise RuntimeError("invalid adjustment factor fields")
        if (factors.filter(
            pl.col("symbol").is_null() | pl.col("trade_date").cast(pl.Date, strict=False).is_null()
            | pl.col("ex_factor").is_null() | ~pl.col("ex_factor").is_finite()
            | (pl.col("ex_factor") <= 0)
        ).height or factors.unique(subset=["symbol", "trade_date"]).height != factors.height):
            raise RuntimeError("invalid adjustment factor values")
        return factors
    return pl.DataFrame()


def validate_stage(stage: Path, *, today: date | None = None) -> dict:
    """Check raw identities/units and as-of capital, one date partition at a time."""
    factors = _validated_factors(stage)
    shares = pl.read_parquet(stage / "financials/shares/part.parquet")
    if not {"symbol", "period_end", "float_shares"} <= set(shares.columns):
        raise RuntimeError("missing share fields")
    invalid_shares = shares.filter(
        pl.col("float_shares").is_not_null()
        & (~pl.col("float_shares").is_finite() | (pl.col("float_shares") <= 0))
    )
    if invalid_shares.height:
        raise RuntimeError("invalid historical share capital")
    instruments = scan_parquet_compat(stage / "instruments/**/*.parquet").collect()
    if instruments.is_empty() or "float_shares" not in instruments.columns:
        raise RuntimeError("missing instrument share fields")
    inst = instruments.select("symbol", "float_shares")
    if inst["symbol"].n_unique() != inst.height:
        raise RuntimeError("duplicate instrument keys")
    daily_dirs = sorted((stage / "kline_daily").glob("date=*"))
    raw_dates = {p.name for p in daily_dirs}
    output_dates = {p.name for p in (stage / "kline_daily_enriched").glob("date=*")}
    if output_dates - raw_dates:
        raise RuntimeError("staged keys contain extra dates")
    rows = missing = partitions = 0
    missing_symbols: set[str] = set()
    for partition in daily_dirs:
        raw = filter_halt_days(scan_daily_parquet(partition / "*.parquet").collect())
        out_dir = stage / "kline_daily_enriched" / partition.name
        if raw.is_empty() and not out_dir.exists():
            continue
        if not out_dir.exists():
            raise RuntimeError("staged keys missing partition")
        out = scan_enriched_parquet(out_dir / "*.parquet").collect()
        raw = raw.sort(["symbol", "date"])
        out = out.sort(["symbol", "date"])
        keys = ["symbol", "date"]
        if (raw.unique(subset=keys).height != raw.height
                or out.unique(subset=keys).height != out.height
                or not raw.select(keys).equals(out.select(keys))):
            raise RuntimeError("staged keys mismatch")
        expected_date = date.fromisoformat(partition.name.removeprefix("date="))
        if raw.filter(pl.col("date") != expected_date).height:
            raise RuntimeError("staged keys have wrong partition date")
        resolved = apply_historical_float_shares(
            raw.join(inst, on="symbol", how="left"), shares, today=today or cn_today(),
        )
        expected = resolved.select(
            (pl.col("volume") * 10_000.0 / pl.col("float_shares")).alias("turnover_rate"),
        )["turnover_rate"]
        checks = [(out["turnover_rate"], expected)]
        checks.extend((out[target], raw[source]) for target, source in (
            ("raw_close", "close"), ("raw_high", "high"), ("raw_low", "low"),
            ("volume", "volume"), ("amount", "amount"),
        ))
        adjusted = _apply_adj_factor(raw, factors).sort(["symbol", "date"])
        checks.extend((out[column], adjusted[column]) for column in ("open", "high", "low", "close"))
        for actual, wanted in checks:
            nulls_equal = actual.is_null().equals(wanted.is_null())
            delta = (actual - wanted).abs()
            tolerance = wanted.abs() * 1e-10 + 1e-10
            if not nulls_equal or ((delta > tolerance) | ~actual.is_finite()).fill_null(False).any():
                raise RuntimeError("staged financial values mismatch")
        for column in ("open", "high", "low", "close", "volume"):
            if out.filter(pl.col(column).is_null() | ~pl.col(column).is_finite() | (pl.col(column) < 0)).height:
                raise RuntimeError("staged financial values invalid")
        missing_rows = out.filter(pl.col("turnover_rate").is_null())
        missing += missing_rows.height
        missing_symbols.update(missing_rows["symbol"].to_list())
        rows += out.height
        partitions += 1
    return {"rows": rows, "partitions": partitions, "missing_turnover_rows": missing,
            "missing_turnover_symbols": len(missing_symbols),
            "missing_turnover_sample": sorted(missing_symbols)[:10]}


def _require_complete_repair(root: Path) -> None:
    completed, complete, coverage = _read_share_history_rebuild_state(root)
    universe = share_history_rebuild_symbols(root)
    if not complete or not universe or set(universe) - completed:
        raise RuntimeError("share repair incomplete; no enriched stage created")
    daily_start = _daily_share_coverage_start(root)
    if coverage is None or daily_start is None or coverage > daily_start:
        raise RuntimeError("share repair coverage insufficient")


def rebuild_enriched_stage(data_dir: Path, *, batch_size: int = 100) -> dict:
    """Require repaired inputs, snapshot them, then run the existing bounded pipeline."""
    if not 1 <= batch_size <= 1000:
        raise ValueError("batch_size must be between 1 and 1000")
    root = data_dir.resolve()
    _require_complete_repair(root)
    input_hashes = _fingerprints(root, _input_files(root))
    live_hashes = _fingerprints(root, sorted((root / "kline_daily_enriched").rglob("*.parquet")))
    parent = root / "maintenance"
    parent.mkdir(exist_ok=True)
    if parent.is_symlink():
        raise RuntimeError("unsafe staging directory")
    stage = Path(tempfile.mkdtemp(prefix="enriched-stage-", dir=parent))
    manifest = {"status": "running", "method_version": "historical-turnover-v1",
                "inputs": input_hashes, "live_enriched": live_hashes,
                "valuation_date": cn_today().isoformat(), "batch_size": batch_size}
    manifest_path = stage / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    try:
        for relative in input_hashes:
            target = stage / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(root / relative, target)
        if _fingerprints(stage, _input_files(stage)) != input_hashes or not inputs_unchanged(root, manifest):
            raise RuntimeError("enriched inputs changed during snapshot")
        _require_complete_repair(stage)
        _validated_factors(stage)
        symbols = (scan_daily_parquet(stage / "kline_daily/**/*.parquet")
                   .select("symbol").drop_nulls().unique().sort("symbol")
                   .collect(engine="streaming")["symbol"].to_list())
        batches = 0
        for offset in range(0, len(symbols), batch_size):
            run_pipeline(stage, symbols=symbols[offset:offset + batch_size])
            batches += 1
            print(json.dumps({"status": "rebuilding", "batch": batches,
                              "total_batches": (len(symbols) + batch_size - 1) // batch_size}), flush=True)
        validation = validate_stage(stage, today=date.fromisoformat(manifest["valuation_date"]))
        report = {"status": "validated", "stage": stage.relative_to(root).as_posix(),
                  "symbols": len(symbols), "batches": batches, **validation,
                  "ready_for_publication": False}
        # Even complete turnover requires backtests, a fresh live-input check,
        # a backup and a controlled publication window. This command never publishes.
        manifest.update(report)
        manifest["outputs"] = _fingerprints(stage, sorted((stage / "kline_daily_enriched").rglob("*.parquet")))
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        return report
    except Exception as exc:
        manifest.update({"status": "failed", "error_type": type(exc).__name__})
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch-size", type=int, default=100)
    args = parser.parse_args()
    try:
        report = rebuild_enriched_stage(Path(settings.data_dir), batch_size=args.batch_size)
    except Exception as exc:
        print(json.dumps({"status": "failed", "error_type": type(exc).__name__}), flush=True)
        return 1
    print(json.dumps(report), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
