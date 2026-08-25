"""盘后管道 + 盘前维表同步。

调度:
  09:10 盘前 — 同步个股维表 instruments (全量覆盖)
  15:30 盘后 — 日K同步 + 增量除权因子 + enriched 计算 + 刷新视图

盘后同步策略:
  日 K: QuoteService 交易时段已实时落盘 → 有数据时跳过 batch,首次拉 1 年区间
  除权因子: 从已有数据最新日期的下一天开始增量获取,避免重复拉取和计算
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import date as _date
from datetime import datetime as _datetime
from datetime import datetime as _dt
from datetime import time as _time
from datetime import timedelta as _timedelta
from datetime import timedelta as _td
from pathlib import Path
from zoneinfo import ZoneInfo

import polars as pl
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.interval import IntervalTrigger

from app.indicators.pipeline import filter_halt_days, run_pipeline
from app.config import settings
from app.services import index_sync, instrument_sync, kline_sync, preferences as _prefs
from app.tickflow.capabilities import Cap, CapabilitySet
from app.tickflow.pools import DEMO_SYMBOLS, get_pool
from app.tickflow.repository import KlineRepository

logger = logging.getLogger(__name__)
BEIJING_TZ = ZoneInfo("Asia/Shanghai")

ProgressCb = Callable[..., None]


class PipelineStageError(RuntimeError):
    """管道有阶段软失败(数据可能陈旧)时抛出, 让上层 job_store 把任务标记为 failed。

    这些阶段单独 try/except 吞掉异常以不中断整条管道, 但一旦失败即代表对应数据陈旧。
    抛出前进度协议已走完(done/100), 故前端进度条正常收尾, 仅终态如实反映为 failed ——
    不再"部分失败却报成功"。
    """

    def __init__(self, errors: list[str], *, data_freshness: dict | None = None) -> None:
        self.errors = errors
        self.data_freshness = data_freshness or {}
        super().__init__("盘后管道部分阶段失败: " + "; ".join(errors))


def required_market_snapshot_date(now: _datetime, schedule: dict[str, int]) -> _date:
    """Return the latest weekday whose daily bar is expected to be complete.

    The daily pipeline is scheduled after the configured close time.  A manual
    run during the session must validate yesterday's snapshot instead of
    incorrectly requiring an unfinished daily bar for today.
    """
    close_time = _time(int(schedule["hour"]), int(schedule["minute"]))
    target = now.date()
    if now.time() < close_time:
        target -= _timedelta(days=1)
    while target.weekday() >= 5:
        target -= _timedelta(days=1)
    return target


def post_close_retry_times(schedule: dict[str, int]) -> list[tuple[int, int]]:
    """Return a small, bounded retry window after the configured pipeline run."""
    base_minutes = int(schedule["hour"]) * 60 + int(schedule["minute"])
    retry_times: list[tuple[int, int]] = []
    for offset in (30, 60, 120):
        minutes = base_minutes + offset
        if minutes >= 24 * 60:
            continue
        retry_times.append((minutes // 60, minutes % 60))
    return retry_times


def _is_pipeline_snapshot_ready(
    repo: KlineRepository,
    target: _date,
    *,
    pull_index: bool,
) -> bool:
    """判断盘后任务是否真的覆盖了启用的日频资产.

    过去这里只检查股票日K/enriched. 股票已更新而指数同步失败时, 定时
    重试会被错误跳过, 导致指数页长期停在旧月份. 指数页面可直接消费
    ``kline_index_daily``, 因此这里检查其原始分区即可.
    """
    latest_daily = repo.latest_daily_date()
    latest_enriched = repo.latest_enriched_date("stock")
    if not latest_daily or latest_daily < target or not latest_enriched or latest_enriched < target:
        return False
    if _prefs.get_pipeline_regime_enabled():
        # regime 缺口也要触发重试/补跑 — 此前只看日K/enriched/指数,
        # regime 步骤软失败后无人兜底, 「市场环境」页会静默停更。
        # 检查本身出错 (如表损坏) 不阻塞判定: 重跑管道也修不了读表错误。
        try:
            from app.services import regime_builder

            latest_regime = regime_builder.get_regime_coverage(
                repo.store.data_dir
            ).get("latest_date")
        except Exception:  # noqa: BLE001
            logger.debug("regime readiness check failed, ignoring", exc_info=True)
        else:
            if not latest_regime or latest_regime < target.isoformat():
                return False
    if pull_index:
        configured = _prefs.get_pipeline_index_symbols()
        if configured:
            index_symbols = [symbol for symbol in configured.replace(",", " ").split() if symbol]
        else:
            index_symbols = _prefs.get_realtime_index_symbols()
        if not index_symbols:
            return False
        latest_by_symbol = repo.latest_daily_dates_asset("index", index_symbols)
        if any(latest_by_symbol.get(symbol) is None or latest_by_symbol[symbol] < target for symbol in index_symbols):
            return False
    return True


def _coerce_snapshot_date(value) -> _date | None:
    if isinstance(value, _datetime):
        return value.date()
    if isinstance(value, _date):
        return value
    if value:
        try:
            return _date.fromisoformat(str(value)[:10])
        except ValueError:
            return None
    return None


def _classify_missing_symbols(
    missing_symbols: list[str],
    instrument_metadata: pl.DataFrame | None,
) -> dict[str, object]:
    """Separate known historical/inactive symbols from an unexplained data gap.

    The instruments feed currently does not populate ``listing_date``.  We
    therefore only classify an instrument as inactive when its authoritative
    name carries an explicit delisting/PT marker; every other missing symbol
    remains unresolved and must not be silently treated as inactive.
    """
    if instrument_metadata is None or instrument_metadata.is_empty() or "symbol" not in instrument_metadata.columns:
        return {
            "inactive_symbol_count": 0,
            "inactive_symbols": [],
            "unresolved_symbol_count": len(missing_symbols),
            "unresolved_symbols": list(missing_symbols),
        }

    columns = [column for column in ("symbol", "name") if column in instrument_metadata.columns]
    metadata = instrument_metadata.select(columns).unique(subset=["symbol"], keep="last")
    metadata_by_symbol = {
        str(row["symbol"]): str(row.get("name") or "")
        for row in metadata.to_dicts()
        if row.get("symbol")
    }
    inactive: list[str] = []
    unresolved: list[str] = []
    for symbol in missing_symbols:
        name = metadata_by_symbol.get(symbol, "")
        upper_name = name.upper()
        # U+9000 is 退.  Keep the escape here because this file is consumed in
        # environments whose source encoding may not be UTF-8.
        if chr(0x9000) in name or upper_name.lstrip("*").startswith("PT"):
            inactive.append(symbol)
        else:
            unresolved.append(symbol)
    return {
        "inactive_symbol_count": len(inactive),
        "inactive_symbols": inactive[:500],
        "unresolved_symbol_count": len(unresolved),
        "unresolved_symbols": unresolved[:500],
        "unresolved_symbols_truncated": len(unresolved) > 500,
    }


def _load_instrument_metadata(repo) -> pl.DataFrame | None:
    """Load the small instrument catalogue used for coverage explanations."""
    try:
        instrument_dir = Path(repo.store.data_dir) / "instruments"
        files = sorted(instrument_dir.rglob("*.parquet"))
        if not files:
            return None
        return pl.read_parquet(files, columns=["symbol", "name"])
    except Exception as exc:  # noqa: BLE001
        logger.debug("instrument metadata unavailable for coverage: %s", exc)
        return None


def build_provider_reconciliation(
    *,
    target_date: _date,
    symbols: list[str],
    daily: pl.DataFrame | None,
    instrument_metadata: pl.DataFrame | None = None,
    history_window_days: int = 30,
) -> dict:
    """Summarize provider history for symbols absent from the target snapshot."""
    expected = sorted({str(symbol) for symbol in symbols if symbol})
    metadata_by_symbol: dict[str, str] = {}
    if instrument_metadata is not None and not instrument_metadata.is_empty():
        columns = [column for column in ("symbol", "name") if column in instrument_metadata.columns]
        if "symbol" in columns:
            metadata = instrument_metadata.select(columns).unique(subset=["symbol"], keep="last")
            metadata_by_symbol = {
                str(row["symbol"]): str(row.get("name") or "")
                for row in metadata.to_dicts()
                if row.get("symbol")
            }

    latest_by_symbol: dict[str, _date] = {}
    if daily is not None and not daily.is_empty() and {"symbol", "date"} <= set(daily.columns):
        frame = daily.select(["symbol", "date"])
        if frame.schema["date"] != pl.Date:
            frame = frame.with_columns(pl.col("date").cast(pl.Date, strict=False))
        latest_rows = (
            frame.drop_nulls(["symbol", "date"])
            .group_by("symbol")
            .agg(pl.col("date").max().alias("latest_date"))
            .to_dicts()
        )
        latest_by_symbol = {
            str(row["symbol"]): row["latest_date"]
            for row in latest_rows
            if row.get("symbol") and row.get("latest_date")
        }

    details: list[dict] = []
    target_count = 0
    recent_count = 0
    historical_only_count = 0
    no_history_count = 0
    for symbol in expected:
        latest = latest_by_symbol.get(symbol)
        if latest is None:
            status = "no_history_available"
            gap_days = None
            no_history_count += 1
        else:
            gap_days = max(0, (target_date - latest).days)
            if latest >= target_date:
                status = "target_date_available"
                target_count += 1
            elif gap_days <= history_window_days:
                status = "recent_history_no_target"
                recent_count += 1
            else:
                status = "historical_only_no_recent"
                historical_only_count += 1
        details.append({
            "symbol": symbol,
            "name": metadata_by_symbol.get(symbol) or symbol,
            "latest_available_date": latest.isoformat() if latest else None,
            "calendar_gap_days": gap_days,
            "status": status,
        })

    return {
        "status": "checked",
        "target_date": target_date.isoformat(),
        "history_window_days": history_window_days,
        "symbols_checked": len(expected),
        "symbols_with_target_date": target_count,
        "symbols_with_recent_history": recent_count,
        "symbols_with_historical_only": historical_only_count,
        "symbols_without_history": no_history_count,
        "symbols_without_recent_history": historical_only_count + no_history_count,
        "details": details[:500],
        "details_truncated": len(details) > 500,
    }


def _provider_reconcile_missing(repo, target_date: _date, symbols: list[str]) -> dict:
    """Ask the selected custom provider for a bounded history window."""
    provider_name = _prefs.get_daily_data_provider()
    if not symbols:
        return {
            "status": "checked",
            "provider": provider_name,
            "target_date": target_date.isoformat(),
            "history_window_days": 30,
            "symbols_checked": 0,
            "symbols_with_target_date": 0,
            "symbols_with_recent_history": 0,
            "symbols_without_recent_history": 0,
            "details": [],
            "details_truncated": False,
        }
    try:
        from app.data_providers import custom as custom_sources

        if not custom_sources.provider_has_dataset(provider_name, "daily"):
            return {
                "status": "not_available",
                "provider": provider_name,
                "target_date": target_date.isoformat(),
                "symbols_checked": 0,
                "symbols_with_target_date": 0,
                "symbols_with_recent_history": 0,
                "symbols_without_recent_history": 0,
                "details": [],
                "details_truncated": False,
            }
        provider = custom_sources.get_provider(provider_name)
        start = _datetime.combine(target_date - _timedelta(days=30), _time.min)
        end = _datetime.combine(target_date, _time.min)
        daily = provider.get_daily(symbols, start, end, asset_type="stock")
        # A bounded request is cheap for the normal case. For symbols still
        # absent, make one full-history request so "no recent bar" is not
        # incorrectly reported as "no history" (providers may cap results).
        recent_symbols = (
            set(daily.get_column("symbol").drop_nulls().cast(pl.Utf8).to_list())
            if daily is not None and "symbol" in daily.columns
            else set()
        )
        missing_from_window = [symbol for symbol in symbols if symbol not in recent_symbols]
        if missing_from_window:
            try:
                historical = provider.get_daily(
                    missing_from_window,
                    None,
                    None,
                    asset_type="stock",
                )
                frames = []
                for frame in (daily, historical):
                    if frame is not None and {"symbol", "date"} <= set(frame.columns):
                        frames.append(frame.select(["symbol", "date"]))
                daily = pl.concat(frames, how="vertical_relaxed") if frames else daily
            except Exception as exc:  # noqa: BLE001
                logger.info("provider historical reconciliation unavailable: %s", type(exc).__name__)
        report = build_provider_reconciliation(
            target_date=target_date,
            symbols=symbols,
            daily=daily,
            instrument_metadata=_load_instrument_metadata(repo),
        )
        report["provider"] = provider_name
        return report
    except Exception as exc:  # noqa: BLE001
        return {
            "status": "unavailable",
            "provider": provider_name,
            "target_date": target_date.isoformat(),
            "symbols_checked": len(set(symbols)),
            "symbols_with_target_date": 0,
            "symbols_with_recent_history": 0,
            "symbols_without_recent_history": len(set(symbols)),
            "details": [],
            "details_truncated": False,
            "error": type(exc).__name__,
        }


def build_snapshot_coverage(
    *,
    target_date: _date,
    universe: list[str],
    provider_date: _date | str | None,
    snapshot: pl.DataFrame | None,
    instrument_metadata: pl.DataFrame | None = None,
) -> dict:
    """Describe provider coverage without filling missing financial rows."""
    expected_symbols = sorted({str(symbol) for symbol in universe if symbol})
    provider_day = _coerce_snapshot_date(provider_date)
    current = snapshot if snapshot is not None else pl.DataFrame()
    if not current.is_empty() and "date" in current.columns:
        date_column = current.get_column("date")
        if date_column.dtype != pl.Date:
            current = current.with_columns(
                pl.col("date").cast(pl.Date, strict=False).alias("date")
            )
        current = current.filter(pl.col("date") == target_date)
    else:
        current = pl.DataFrame()

    available_symbols = (
        set(current.get_column("symbol").drop_nulls().cast(pl.Utf8).to_list())
        if "symbol" in current.columns
        else set()
    )
    missing_symbols = [symbol for symbol in expected_symbols if symbol not in available_symbols]
    if provider_day is None:
        status = "unavailable"
    elif provider_day < target_date:
        status = "waiting"
    elif missing_symbols:
        status = "partial"
    else:
        status = "ready"

    report = {
        "status": status,
        "target_date": target_date.isoformat(),
        "provider_date": provider_day.isoformat() if provider_day else None,
        "requested_symbol_count": len(expected_symbols),
        "available_symbol_count": len(available_symbols),
        "available_rows": current.height,
        "missing_symbol_count": len(missing_symbols),
        "missing_symbols": missing_symbols[:500],
        "missing_symbols_truncated": len(missing_symbols) > 500,
    }
    report.update(_classify_missing_symbols(missing_symbols, instrument_metadata))
    return report


def _provider_snapshot_coverage(repo, target_date: _date, universe: list[str]) -> dict:
    """Read one provider snapshot to explain freshness failures precisely."""
    provider_name = _prefs.get_daily_data_provider()
    instrument_metadata = _load_instrument_metadata(repo)
    try:
        from app.services.market_overview_builder import _dashboard_daily_snapshot

        provider_date, snapshot = _dashboard_daily_snapshot(repo)
        report = build_snapshot_coverage(
            target_date=target_date,
            universe=universe,
            provider_date=provider_date,
            snapshot=snapshot,
            instrument_metadata=instrument_metadata,
        )
    except Exception as exc:
        unique_universe = sorted(set(universe))
        report = {
            "status": "unavailable",
            "target_date": target_date.isoformat(),
            "provider_date": None,
            "requested_symbol_count": len(unique_universe),
            "available_symbol_count": 0,
            "available_rows": 0,
            "missing_symbol_count": len(unique_universe),
            "missing_symbols": unique_universe[:500],
            "missing_symbols_truncated": len(unique_universe) > 500,
            "error": type(exc).__name__,
        }
        report.update(_classify_missing_symbols(unique_universe, instrument_metadata))
    report["source"] = provider_name
    report["provider"] = provider_name
    report["provider_reconciliation"] = _provider_reconcile_missing(
        repo,
        target_date,
        report.get("unresolved_symbols", []),
    )
    try:
        persisted_daily = repo.latest_daily_date()
        persisted_enriched = repo.latest_enriched_date("stock")
    except Exception:
        persisted_daily = None
        persisted_enriched = None
    report["persisted_daily_date"] = persisted_daily.isoformat() if persisted_daily else None
    report["persisted_enriched_date"] = persisted_enriched.isoformat() if persisted_enriched else None
    report["persistence_status"] = (
        "ready"
        if persisted_daily and persisted_enriched
        and persisted_daily >= target_date
        and persisted_enriched >= target_date
        else "pending"
    )
    return report


def _persisted_snapshot_coverage(repo, target_date: _date, universe: list[str]) -> dict:
    """Report which requested symbols actually have a persisted target-day bar."""
    instrument_metadata = _load_instrument_metadata(repo)
    try:
        rows = repo.db.execute(
            "SELECT DISTINCT symbol FROM kline_daily WHERE date = ? ORDER BY symbol",
            [target_date],
        ).fetchall()
        symbols = [str(row[0]) for row in rows if row and row[0]]
        snapshot = pl.DataFrame({
            "symbol": symbols,
            "date": [target_date] * len(symbols),
        })
        report = build_snapshot_coverage(
            target_date=target_date,
            universe=universe,
            provider_date=target_date,
            snapshot=snapshot,
            instrument_metadata=instrument_metadata,
        )
    except Exception as exc:
        report = {
            "status": "unavailable",
            "target_date": target_date.isoformat(),
            "provider_date": None,
            "requested_symbol_count": len(set(universe)),
            "available_symbol_count": 0,
            "available_rows": 0,
            "missing_symbol_count": len(set(universe)),
            "missing_symbols": sorted(set(universe))[:500],
            "missing_symbols_truncated": len(set(universe)) > 500,
            "error": type(exc).__name__,
        }
        report.update(_classify_missing_symbols(sorted(set(universe)), instrument_metadata))
    report["source"] = "persisted"
    report["provider"] = _prefs.get_daily_data_provider()
    try:
        persisted_daily = repo.latest_daily_date()
        persisted_enriched = repo.latest_enriched_date("stock")
    except Exception:
        persisted_daily = None
        persisted_enriched = None
    report["persisted_daily_date"] = persisted_daily.isoformat() if persisted_daily else None
    report["persisted_enriched_date"] = persisted_enriched.isoformat() if persisted_enriched else None
    report["persistence_status"] = (
        "ready"
        if persisted_daily and persisted_enriched
        and persisted_daily >= target_date
        and persisted_enriched >= target_date
        else "pending"
    )
    report["provider_reconciliation"] = _provider_reconcile_missing(
        repo,
        target_date,
        report.get("unresolved_symbols", []),
    )
    return report


def pipeline_error_details(exc: Exception) -> dict:
    if isinstance(exc, PipelineStageError):
        return {
            "type": "pipeline_stage_error",
            "stage_errors": list(exc.errors),
            "data_freshness": dict(exc.data_freshness),
        }
    return {"type": type(exc).__name__, "message": str(exc)}


def validate_market_snapshot_freshness(
    repo: KlineRepository,
    target_date: _date,
    *,
    require_enriched: bool,
) -> list[str]:
    """确认任务声称覆盖的交易日已真实落库，避免空响应误报同步成功。"""
    errors: list[str] = []
    latest_daily = repo.latest_daily_date()
    if latest_daily is None or latest_daily < target_date:
        errors.append(
            f"daily freshness: expected {target_date.isoformat()}, got "
            f"{latest_daily.isoformat() if latest_daily else 'none'}"
        )
    if require_enriched:
        latest_enriched = repo.latest_enriched_date("stock")
        if latest_enriched is None or latest_enriched < target_date:
            errors.append(
                f"enriched freshness: expected {target_date.isoformat()}, got "
                f"{latest_enriched.isoformat() if latest_enriched else 'none'}"
            )
    return errors


def _noop(stage: str, pct: int, msg: str, **kwargs) -> None:  # noqa: ARG001
    pass


def _invalidate(table: str | None = None) -> None:
    """stage 写完调用,让 /api/data/status 只重算被影响的那张表。"""
    from app.api.data import invalidate_data_cache
    invalidate_data_cache(table)


def _resolve_universe(capset: CapabilitySet, repo=None) -> list[str]:
    """解析标的池 — 以 CN_Equity_A (沪深京A股 ~5522只) 为主。

    有 batch 能力 → 直接拉 CN_Equity_A universe
    其他用户 → 用 instruments parquet + watchlist 兜底

    repo 传入时过滤自选兜底里的指数 symbol (指数日K走独立 kline_index_* 存储,
    进股票池会污染 kline_daily/kline_minute)。ETF 刻意保留 (既有行为)。
    """
    if capset.has(Cap.KLINE_DAILY_BATCH):
        try:
            all_a = get_pool("CN_Equity_A", refresh=True)
            if all_a:
                return sorted(all_a)
        except Exception as e:  # noqa: BLE001
            logger.warning("CN_Equity_A pool unavailable, fallback: %s", e)

    # Free 用户兜底: instruments parquet + watchlist + demo
    base: set[str] = set(DEMO_SYMBOLS)
    base.update(get_pool("watchlist"))
    d = Path(settings.data_dir)
    inst_path = d / "instruments" / "instruments.parquet"
    if inst_path.exists():
        try:
            inst = pl.read_parquet(inst_path, columns=["symbol"])
            base.update(inst["symbol"].to_list())
        except Exception as e:  # noqa: BLE001
            logger.warning("instruments supplement failed: %s", e)
    # 过滤自选兜底里的指数 symbol (指数日K走独立 kline_index_* 存储,
    # 进股票池会污染 kline_daily/kline_minute)。ETF 刻意保留 (既有行为)。
    if repo is not None:
        base -= set(repo.get_index_symbol_set())
    return sorted(base)


def _gap_fill_index_snapshot(
    repo: KlineRepository,
    today: _date,
    now: _datetime,
    *,
    pull_index: bool,
    emit: ProgressCb,
    stage_errors: list[str],
) -> int:
    """盘后补齐缺失的核心指数当日分区。

    指数快照补缺不能依赖 ``KLINE_DAILY_BATCH``: 免费/无 TickFlow Key
    的部署同样需要当天的指数看板。按标准代码检查每只指数，不能因
    当日分区里已有一只就跳过其他缺口。配置了自定义日线源时优先通过
    provider 契约补齐；只有 TickFlow 模式才保留新浪快照降级。
    """
    if not pull_index or today.weekday() >= 5 or now.time() < _time(15, 10):
        return 0

    try:
        configured = _prefs.get_pipeline_index_symbols()
        idx_symbols = (
            [symbol for symbol in configured.replace(",", " ").split() if symbol]
            if isinstance(configured, str)
            else [str(symbol) for symbol in (configured or []) if symbol]
        )
        if not idx_symbols:
            realtime_symbols = _prefs.get_realtime_index_symbols()
            idx_symbols = (
                [symbol for symbol in realtime_symbols.replace(",", " ").split() if symbol]
                if isinstance(realtime_symbols, str)
                else [str(symbol) for symbol in (realtime_symbols or []) if symbol]
            )
        if not idx_symbols:
            idx_inst = repo.get_index_instruments()
            idx_symbols = (
                sorted(set(idx_inst["symbol"].to_list()))
                if not idx_inst.is_empty() and "symbol" in idx_inst.columns
                else []
            )
        if not idx_symbols:
            logger.warning("sync_index: no index symbols available for snapshot gap-fill")
            return 0

        latest_by_symbol = repo.latest_daily_dates_asset("index", idx_symbols)
        missing_symbols = [
            symbol
            for symbol in idx_symbols
            if latest_by_symbol.get(symbol) is None or latest_by_symbol[symbol] < today
        ]
        if not missing_symbols:
            return 0

        provider_name = _prefs.get_daily_data_provider()
        emit("sync_index", 88, f"补齐 {len(missing_symbols)} 只指数当日日K…")
        if provider_name != "tickflow":
            from app.data_providers import custom as custom_sources

            if not custom_sources.provider_has_dataset(provider_name, "daily"):
                logger.warning("sync_index: provider %s has no daily dataset", provider_name)
                return 0
            provider = custom_sources.get_provider(provider_name)
            boundary = _datetime.combine(today, _time.min)
            ispot = provider.get_daily(
                missing_symbols,
                start_time=boundary,
                end_time=boundary,
                asset_type="index",
            )
        else:
            from app.services import sina_snapshot

            provider_name = "sina"
            ispot = sina_snapshot.fetch_spot_daily(missing_symbols, asset_type="index")
        if not ispot.is_empty():
            if ispot.schema.get("date") == pl.String:
                ispot = ispot.with_columns(pl.col("date").str.to_date(strict=False))
            elif ispot.schema.get("date") != pl.Date:
                ispot = ispot.with_columns(pl.col("date").cast(pl.Date, strict=False))
            ispot = ispot.filter(
                (pl.col("date") == today)
                & pl.col("symbol").is_in(missing_symbols)
            )
            ispot = filter_halt_days(ispot)
        if ispot.is_empty():
            logger.warning("sync_index: %s returned no missing index rows for %s", provider_name, today)
            return 0

        repo.merge_live_daily_asset("index", ispot)
        repo.refresh_index_views()
        _invalidate("index_daily")
        emit("sync_index", 88, f"指数当日日K已用快照补齐,{ispot.height} 只")
        logger.info(
            "sync_index: %s gap-fill %d/%d missing indexes for %s",
            provider_name,
            ispot.height,
            len(missing_symbols),
            today,
        )
        return ispot.height
    except Exception as e:  # noqa: BLE001
        logger.warning("index gap-fill failed: %s", e)
        stage_errors.append(f"index gap fill: {e}")
        return 0


def run_instruments_sync(repo: KlineRepository) -> dict:
    """盘前同步个股维表。

    维表含当日涨跌停价 (limit_up/down), 同步完成后刷新 enriched 内存缓存,
    确保跨天后连板梯队/选股等读到的是基于最新维表的数据 (而非前一交易日残留)。
    """
    rows = instrument_sync.sync_instruments(repo.store.data_dir)
    _refresh_instruments_view(repo)
    _invalidate("instruments")
    # 维表更新后重建 enriched 缓存 (clear + refresh, 与设置页「清理并刷新」同等效果)
    if rows > 0:
        repo.clear_cache()
        repo.refresh_cache()
    return {"instruments_rows": rows}


def run_now(
    repo: KlineRepository,
    capset: CapabilitySet,
    on_progress: ProgressCb | None = None,
    override_start_date: _date | None = None,
) -> dict:
    """立即执行一次盘后管道,支持进度回调。

    跳过的 stage **不 emit**,避免前端把"无 capability"的卡片错误标记为 active/done。
    result 里带 skipped_stages 列表供前端展示。

    override_start_date: 传入时强制走 batch 拉取分支,用该日期作为日K/除权/指数的
        拉取起点(到今天),用于「数据修正/补数据」场景。None 时走原有自动判定逻辑。
    """
    emit = on_progress or _noop
    skipped: list[str] = []
    # 阶段软失败累积: 下列阶段 try/except 吞异常以不中断管道, 但失败即代表数据可能陈旧。
    # 管道末尾若非空则抛 PipelineStageError, 让任务终态如实标记为 failed(而非误报成功)。
    stage_errors: list[str] = []

    # Step 0: 先同步个股维表, 再解析标的池 — 确保标的池基于最新 instruments
    emit("sync_instruments", 2, "同步个股维表…")
    inst_rows = instrument_sync.sync_instruments(repo.store.data_dir)
    if inst_rows > 0:
        _refresh_instruments_view(repo)
    emit("sync_instruments", 8, f"个股维表同步完成,{inst_rows} 只标的")
    _invalidate("instruments")

    emit("resolve_universe", 9, "解析标的池…")
    universe = _resolve_universe(capset, repo)
    emit("resolve_universe", 10, f"标的池规模:{len(universe)} 只")

    # Step 1: 日 K 同步
    #   override_start_date 传入 → 强制 batch 拉取 [override_start_date ~ today] (数据修正)
    #   付费档 + 今天有数据 → 实时行情接口拉一次覆写（1请求全市场）
    #   有历史数据 → batch K-line API 补齐缺口
    #   无任何数据 → batch K-line API 拉首次 1 年
    latest_daily = repo.latest_daily_date()
    now = _datetime.now(BEIJING_TZ)
    today = now.date()
    today_exists = latest_daily and latest_daily >= today
    new_daily_days = 0
    # 日K范围拉取的起点(分支3补缺口/分支4首次/数据修正); 实时增量/跳过时为 None。
    # 供 Step 1.5 除权因子回溯范围对齐: 范围拉取→用日K范围, 非范围→最近N天兜底。
    daily_range_start: _date | None = None

    # A 股日K拉取开关(默认开);关闭时跳过日K同步,保留已有数据。
    # 数据修正(override_start_date)时即使关闭开关也强制拉取 — 修正就是来补数据的。
    pull_a_share = _prefs.get_pipeline_pull_a_share()
    if not pull_a_share and not override_start_date:
        emit("sync_daily", 45, "已跳过 A 股日K同步(拉取内容未勾选)")
        logger.info("sync_daily: skipped (pipeline_pull_a_share=False)")
    elif override_start_date:
        # 数据修正: 强制用传入日期作起点 batch 拉取, 忽略实时行情覆写分支。
        start_date = override_start_date
        daily_range_start = start_date
        emit("sync_daily", 12, f"获取日K [{start_date} ~ {today}]…")
        logger.info("sync_daily: [%s ~ %s] repair/override", start_date, today)

        def _daily_chunk_progress(cur: int, tot: int) -> None:
            emit("sync_daily", 12 + int(33 * cur / tot),
                 f"日K 批次 {cur}/{tot}", stage_pct=int(100 * cur / tot), skip_log=True)
        written_daily = kline_sync.sync_and_persist_daily_batch(
            universe, repo, capset,
            start_date=_datetime.combine(start_date, _datetime.min.time()),
            end_date=_datetime.combine(today, _datetime.min.time()),
            on_chunk_done=_daily_chunk_progress,
        )
        gap_days = (today - start_date).days
        new_daily_days = gap_days
        emit("sync_daily", 45, f"日K 完成,覆盖 {gap_days} 天")
        logger.info("sync_daily: [%s ~ %s] done, %d days", start_date, today, gap_days)
    elif today_exists and capset.has(Cap.QUOTE_POOL) and _prefs.get_daily_data_provider() == "tickflow":
        # 付费档:今天有数据(QuoteService 已落盘)→ 实时行情覆写,确保最新。
        # free/none 档无 quote.pool 能力,即便今天已有数据(如从 expert 降级),
        # 也降级到下方 batch 路径刷新,避免调用无权限的实时行情接口。
        emit("sync_daily", 12, f"获取日K [{today} ~ {today}] 实时行情…")
        written_daily = kline_sync.sync_daily_by_quotes(repo)
        new_daily_days = 1
        emit("sync_daily", 45, f"日K 完成,{written_daily} 只标的")
        logger.info("sync_daily: [%s ~ %s] live quotes, %d symbols", today, today, written_daily)
    elif latest_daily:
        # 有历史 → batch 补齐缺口。
        # 也覆盖"今天已有数据但无实时行情权限(free/none)"的降级场景:
        #   此时 start_date = latest_daily = today,batch 刷新当天日K。
        start_date = latest_daily
        daily_range_start = start_date
        emit("sync_daily", 12, f"获取日K [{start_date} ~ {today}]…")
        logger.info("sync_daily: [%s ~ %s] %s", start_date, today,
                    "refresh today" if today_exists else "gap fill")

        def _daily_chunk_progress(cur: int, tot: int) -> None:
            emit("sync_daily", 12 + int(33 * cur / tot),
                 f"日K 批次 {cur}/{tot}", stage_pct=int(100 * cur / tot), skip_log=True)
        written_daily = kline_sync.sync_and_persist_daily_batch(
            universe, repo, capset,
            start_date=_datetime.combine(start_date, _datetime.min.time()),
            end_date=_datetime.combine(today, _datetime.min.time()),
            on_chunk_done=_daily_chunk_progress,
        )
        gap_days = (today - start_date).days
        new_daily_days = gap_days
        emit("sync_daily", 45, f"日K 完成,覆盖 {gap_days} 天")
        logger.info("sync_daily: [%s ~ %s] done, %d days", start_date, today, gap_days)
    else:
        # 首次：无任何数据 → batch 拉 1 年
        start_date = today - _td(days=365)
        daily_range_start = start_date
        emit("sync_daily", 12, f"获取日K [{start_date} ~ {today}]…")
        logger.info("sync_daily: [%s ~ %s] initial fetch", start_date, today)

        def _daily_chunk_progress(cur: int, tot: int) -> None:
            emit("sync_daily", 12 + int(33 * cur / tot),
                 f"日K 批次 {cur}/{tot}", stage_pct=int(100 * cur / tot), skip_log=True)
        written_daily = kline_sync.sync_and_persist_daily_batch(
            universe, repo, capset,
            start_date=_datetime.combine(start_date, _datetime.min.time()),
            end_date=_datetime.combine(today, _datetime.min.time()),
            on_chunk_done=_daily_chunk_progress,
        )
        new_daily_days = 365
        emit("sync_daily", 45, "日K 完成")
        logger.info("sync_daily: [%s ~ %s] done", start_date, today)
    _invalidate("daily")

    # Step 1.6: 当日日K补缺 — tickflow 免费档 / TeaJoin 日K 均为 T+1 发布
    # (当日收盘数据次日才可见), 收盘后本地仍缺当日分区时, 用新浪快照行情补齐。
    # 次日 batch 同步会以 merge-upsert 覆写该分区为权威数据, 不留脏数据。
    if (
        not override_start_date
        and pull_a_share
        and today.weekday() < 5
        and now.time() >= _time(15, 10)
        and (repo.latest_daily_date() or _date.min) < today
    ):
        try:
            emit("sync_daily", 46, "官方源尚未发布今日日K,用快照行情补齐当日…")
            from app.services import sina_snapshot
            spot = sina_snapshot.fetch_spot_daily(universe)
            if not spot.is_empty():
                spot = spot.filter(pl.col("date") == today.isoformat())
                spot = spot.with_columns(pl.col("date").str.to_date())
                spot = filter_halt_days(spot)
            if not spot.is_empty():
                repo.flush_live_daily(spot)
                new_daily_days = max(new_daily_days, 1)
                emit("sync_daily", 46, f"当日日K已用快照补齐,{spot.height} 只标的")
                logger.info("sync_daily: sina snapshot gap-fill %d symbols for %s",
                            spot.height, today)
            else:
                logger.warning("sync_daily: sina snapshot gap-fill 无 %s 当日数据", today)
        except Exception as e:  # noqa: BLE001
            logger.warning("sina snapshot gap-fill failed: %s", e)
            stage_errors.append(f"sina daily gap fill: {e}")

    # 单标的新鲜度: 全局 max(date) 会被任一有今日数据的标的"拉高", 掩盖停牌/复牌/
    # 一直拉失败而掉队的个股缺口(全局判据只刷"今天", 永不回补掉队标的的历史缺口)。
    # 这里检测并**可见化**(WARNING + 计入结果), 让掉队标的不再隐形。
    # (自动回补暂不做 —— 需带退市判定, 否则对已退市标的每轮空拉浪费 API 额度。)
    lagging_symbols: list[str] = []
    if pull_a_share and latest_daily:
        try:
            lagging_symbols = repo.symbols_lagging(today, min_gap_days=3)
            if lagging_symbols:
                logger.warning("日K新鲜度: %d 只标的落后 >3 日 (停牌/退市/拉取失败; 样例: %s)",
                               len(lagging_symbols), lagging_symbols[:10])
        except Exception as e:  # noqa: BLE001
            logger.warning("laggard detection failed: %s", e)
            stage_errors.append(f"laggard detection: {e}")

    # Step 1.5: 同步除权因子 — 范围与日K拉取方式对齐
    #   日K范围拉取(补缺口/首次) → 除权用日K范围 [daily_range_start, now]
    #     首次会覆盖整个日K区间内的历史除权事件; 补缺口天然只增量(起点=latest_daily≈昨天)
    #   日K实时增量/跳过(分支2/分支1) → 除权兜底拉最近 30 天, 补可能遗漏的新除权
    #     (这两类分支不拉历史日K, 除权不能用日K范围, 只能兜底最近几日)
    written_adj = 0
    affected_symbols: list[str] = []
    adj_provider = _prefs.get_adj_factor_provider()
    if adj_provider == "same_as_daily":
        adj_provider = _prefs.get_daily_data_provider()
    can_sync_adj = capset.has(Cap.ADJ_FACTOR) or adj_provider != "tickflow"
    if can_sync_adj:
        from datetime import datetime, timedelta
        adj_end = datetime.now()
        if daily_range_start is not None:
            adj_start = datetime.combine(daily_range_start, datetime.min.time())
        else:
            # 日K实时增量/跳过时, 除权兜底拉最近 N 天, 覆盖周末/长假/停机期间的新除权事件。
            # 15 天: 覆盖春节/国庆最长约10天长假 + 故障恢复缓冲; sync_adj_factor 内部 merge+unique 幂等, 多拉无副作用。
            adj_start = adj_end - timedelta(days=15)
        adj_start_str = adj_start.strftime("%Y-%m-%d")
        adj_end_str = adj_end.strftime("%Y-%m-%d")
        emit("sync_adj", 50, f"获取除权因子 [{adj_start_str} ~ {adj_end_str}]…")
        logger.info("sync_adj: [%s ~ %s] start", adj_start_str, adj_end_str)

        def _adj_chunk_progress(cur: int, tot: int) -> None:
            emit("sync_adj", 50 + int(10 * cur / tot),
                 f"除权因子批次 {cur}/{tot}", stage_pct=int(100 * cur / tot), skip_log=True)
        written_adj, affected_symbols = kline_sync.sync_adj_factor(
            universe, repo, capset,
            start_time=adj_start, end_time=adj_end,
            on_chunk_done=_adj_chunk_progress,
        )
        if affected_symbols:
            _refresh_single_view(repo, "adj_factor")
            emit("sync_adj", 60, f"除权因子完成,新增 {len(affected_symbols)} 只个股")
            logger.info("sync_adj: [%s ~ %s] done, %d symbols", adj_start_str, adj_end_str, len(affected_symbols))
        else:
            emit("sync_adj", 60, "除权因子完成,无新增")
            logger.info("sync_adj: [%s ~ %s] no new factors", adj_start_str, adj_end_str)
        _invalidate("adj_factor")
    else:
        skipped.append("sync_adj")
        logger.info("sync_adj skipped: no ADJ_FACTOR capability")

    # Step 2: 计算 enriched
    #   判断策略:
    #     - 首次 (enriched 目录不存在) → 全量
    #     - 往前扩展历史 (新日期 < enriched 已有最早日期) → 全量
    #       前面的除权因子会改变累积因子链,影响后面所有日期的复权价格
    #     - 往后新增日期 (新日期 > enriched 已有最晚日期)
    #       → 增量补新区块(所有标的) + 受除权影响个股全日期重算
    #     - 无新日期 + 有新除权因子 → 增量: 只重算受影响个股的全部日期
    #     - 无新日期 + 无变化 → 跳过
    enriched_dir = repo.store.data_dir / "kline_daily_enriched"
    enriched_exists = enriched_dir.exists() and any(enriched_dir.glob("date=*"))
    daily_dir = repo.store.data_dir / "kline_daily"
    daily_days = len(list(daily_dir.glob("date=*"))) if daily_dir.exists() else 0
    prev_enriched_days = len(list(enriched_dir.glob("date=*"))) if enriched_exists else 0

    # 判断新日期方向: 找 daily 和 enriched 的日期集合做比较
    forward_incremental = False
    backward_extension = False

    if daily_days > prev_enriched_days and enriched_exists:
        daily_dates = sorted(d.stem.split("=")[1] for d in daily_dir.glob("date=*"))
        enriched_dates = sorted(d.stem.split("=")[1] for d in enriched_dir.glob("date=*"))
        earliest_enriched = enriched_dates[0]
        latest_enriched = enriched_dates[-1]
        new_dates = set(daily_dates) - set(enriched_dates)
        if new_dates:
            # 有新日期早于 enriched 最早日期 → 往前扩展
            if any(d < earliest_enriched for d in new_dates):
                backward_extension = True
            # 有新日期晚于 enriched 最晚日期 → 往后新增
            if any(d > latest_enriched for d in new_dates):
                forward_incremental = True

    def _enriched_batch_progress(cur: int, tot: int) -> None:
        emit("compute_enriched", 65 + int(23 * cur / tot),
             f"计算指标 批次 {cur}/{tot}", stage_pct=int(100 * cur / tot), skip_log=True)

    if not enriched_exists or backward_extension:
        # 首次 或 往前扩展 → 全量
        emit("compute_enriched", 65, "全量计算 enriched…")
        logger.info("compute_enriched: full rebuild (first=%s, backward=%s, daily=%d, enriched=%d)",
                    not enriched_exists, backward_extension, daily_days, prev_enriched_days)
        written_enriched = run_pipeline(on_batch_done=_enriched_batch_progress)
        new_enriched_days = len(list(enriched_dir.glob("date=*")))
        emit("compute_enriched", 88, f"enriched 完成,覆盖 {new_enriched_days} 天")
        logger.info("compute_enriched: full rebuild done, %d days", new_enriched_days)
    elif forward_incremental:
        # 往后新增日期: 增量补新区块 + 受影响个股全日期重算
        symbols_to_recompute = list(set(affected_symbols)) if affected_symbols else []
        emit("compute_enriched", 65,
             f"增量计算 enriched (新日期 + {len(symbols_to_recompute)} 只个股重算)…"
             if symbols_to_recompute else "增量计算 enriched (新日期)…")
        logger.info("compute_enriched: forward incremental, %d symbols to recompute",
                    len(symbols_to_recompute))
        written_enriched = run_pipeline(
            new_dates_only=True,
            symbols=symbols_to_recompute or None,
            on_batch_done=_enriched_batch_progress,
        )
        new_enriched_days = len(list(enriched_dir.glob("date=*")))
        emit("compute_enriched", 88, f"enriched 完成,覆盖 {new_enriched_days} 天")
        logger.info("compute_enriched: forward incremental done, %d days", new_enriched_days)
    elif affected_symbols:
        # 无新日期,仅除权因子变更 → 只重算受影响个股的全部日期
        emit("compute_enriched", 65, f"增量计算 enriched ({len(affected_symbols)} 只个股)…")
        logger.info("compute_enriched: adj_factor incremental, %d symbols", len(affected_symbols))
        written_enriched = run_pipeline(symbols=affected_symbols, on_batch_done=_enriched_batch_progress)
        emit("compute_enriched", 88, f"enriched 完成,{len(affected_symbols)} 只个股")
    else:
        written_enriched = 0
        logger.info("compute_enriched: skip (no new daily, no adj_factor changes)")
    _refresh_single_view(repo, "kline_enriched")
    _invalidate("enriched")

    # Step 2.3: 指数 / ETF 同步 — 物理分开存储；ETF 可复权，指数不复权。
    written_index_daily = 0
    written_etf_daily = 0
    index_count = 0
    etf_count = 0
    etf_adj_symbols = 0
    pull_index = _prefs.get_pipeline_pull_index()
    pull_etf = _prefs.get_pipeline_pull_etf()

    # tickflow 免费档无批量日K能力时, ETF 日K仍可走自定义源 (如 teajoin fund_daily);
    # 指数日K维持原能力门禁不变。
    etf_via_custom = False
    if pull_etf and not capset.has(Cap.KLINE_DAILY_BATCH):
        _daily_provider = _prefs.get_daily_data_provider()
        if _daily_provider != "tickflow":
            from app.data_providers import custom as custom_sources
            try:
                etf_via_custom = custom_sources.provider_has_dataset(_daily_provider, "daily")
            except Exception:  # noqa: BLE001
                etf_via_custom = False

    if (capset.has(Cap.KLINE_DAILY_BATCH) and (pull_index or pull_etf)) or (pull_etf and etf_via_custom):
        _types = []
        if pull_index:
            _types.append("指数")
        if pull_etf:
            _types.append("ETF")
        emit("sync_index", 88, f"同步{'+'.join(_types)}日K…")
        # 子阶段进度分配: 88.0(开始) → 89.0(完成), 指数占前半, ETF 占后半
        try:
            if pull_index and capset.has(Cap.KLINE_DAILY_BATCH):
                emit("sync_index", 88, "同步指数维表…")
                index_count = index_sync.sync_index_instruments(repo, pull_index=True, pull_etf=False)
                emit("sync_index", 88, f"指数维表完成,{index_count} 只")
                index_dir = repo.store.data_dir / "kline_index_enriched"
                index_dates = sorted(
                    d.name[5:] for d in index_dir.glob("date=*")
                    if d.is_dir() and d.name.startswith("date=")
                ) if index_dir.exists() else []
                # 数据修正模式下用传入起点; 否则用本地指数最新日期补到今天
                if override_start_date:
                    index_start = override_start_date
                else:
                    index_start = _date.fromisoformat(index_dates[-1]) if index_dates else today - _td(days=365)

                def _index_chunk(cur: int, tot: int) -> None:
                    emit("sync_index", 88, f"指数日K批次 {cur}/{tot}",
                         stage_pct=int(100 * cur / tot) if tot else 100, skip_log=cur < tot)

                written_index_daily = index_sync.sync_and_persist_index_daily(
                    repo,
                    capset,
                    start_date=_dt.combine(index_start, _dt.min.time()),
                    end_date=_dt.combine(today, _dt.min.time()),
                    on_chunk_done=_index_chunk,
                )
                emit("sync_index", 88, f"指数日K完成,{written_index_daily} 行")
                _invalidate("index_instruments")
                _invalidate("index_daily")
                _invalidate("index_enriched")

                # 指数当日补缺: 同 Step 1.6, 官方指数日K同样 T+1 发布,
                # 收盘后缺当日分区时用新浪快照补齐, 次日同步覆写为权威数据。
                idx_daily_dir = repo.store.data_dir / "kline_index_daily"
                idx_dates = sorted(
                    d.name[5:] for d in idx_daily_dir.glob("date=*")
                    if d.is_dir() and d.name.startswith("date=")
                ) if idx_daily_dir.exists() else []
                idx_latest = _date.fromisoformat(idx_dates[-1]) if idx_dates else None
                if (
                    today.weekday() < 5
                    and now.time() >= _time(15, 10)
                    and (idx_latest or _date.min) < today
                ):
                    try:
                        idx_inst = repo.get_index_instruments()
                        idx_symbols = (
                            sorted(set(idx_inst["symbol"].to_list()))
                            if not idx_inst.is_empty() and "symbol" in idx_inst.columns
                            else []
                        )
                        if idx_symbols:
                            emit("sync_index", 88, "官方源尚未发布今日指数日K,用快照行情补齐…")
                            from app.services import sina_snapshot
                            ispot = sina_snapshot.fetch_spot_daily(idx_symbols, asset_type="index")
                            if not ispot.is_empty():
                                ispot = ispot.filter(pl.col("date") == today.isoformat())
                                ispot = ispot.with_columns(pl.col("date").str.to_date())
                                ispot = filter_halt_days(ispot)
                            if not ispot.is_empty():
                                repo.flush_live_daily_asset("index", ispot)
                                emit("sync_index", 88, f"指数当日日K已用快照补齐,{ispot.height} 只")
                                logger.info("sync_index: sina snapshot gap-fill %d indexes for %s",
                                            ispot.height, today)
                            else:
                                logger.warning("sync_index: sina snapshot gap-fill 无 %s 当日指数数据", today)
                    except Exception as e:  # noqa: BLE001
                        logger.warning("sina index gap-fill failed: %s", e)
                        stage_errors.append(f"sina index gap fill: {e}")

            if pull_etf:
                emit("sync_index", 88, "同步 ETF 维表…")
                etf_count = index_sync.sync_etf_instruments(repo)
                emit("sync_index", 88, f"ETF 维表完成,{etf_count} 只")
                etf_symbols: list[str] = []
                etf_inst = repo.get_etf_instruments()
                if not etf_inst.is_empty() and "symbol" in etf_inst.columns:
                    etf_symbols = sorted(set(etf_inst["symbol"].to_list()))
                if etf_symbols and capset.has(Cap.ADJ_FACTOR):
                    try:
                        emit("sync_index", 88, "同步 ETF 除权因子…")
                        from datetime import datetime, timedelta
                        adj_end = datetime.now()
                        adj_path = repo.store.data_dir / "adj_factor_etf" / "all.parquet"
                        fallback_start = adj_end - timedelta(days=30)
                        adj_start = fallback_start
                        if adj_path.exists():
                            max_date = pl.scan_parquet(adj_path).select(pl.col("trade_date").max()).collect().item()
                            if max_date is not None:
                                if isinstance(max_date, str):
                                    adj_start = datetime.combine(_date.fromisoformat(max_date), datetime.min.time())
                                elif isinstance(max_date, datetime):
                                    adj_start = datetime.combine(max_date.date(), datetime.min.time())
                                else:
                                    adj_start = datetime.combine(max_date, datetime.min.time())
                        _, affected_etfs = index_sync.sync_etf_adj_factor(
                            etf_symbols,
                            repo,
                            capset,
                            start_time=adj_start,
                            end_time=adj_end,
                        )
                        etf_adj_symbols = len(affected_etfs)
                        emit("sync_index", 88, f"ETF 除权因子完成,{etf_adj_symbols} 只")
                    except Exception as e:  # noqa: BLE001
                        logger.warning("ETF adj_factor skipped: %s", e)
                        stage_errors.append(f"ETF adj_factor: {e}")
                etf_dir = repo.store.data_dir / "kline_etf_enriched"
                etf_dates = sorted(
                    d.name[5:] for d in etf_dir.glob("date=*")
                    if d.is_dir() and d.name.startswith("date=")
                ) if etf_dir.exists() else []
                etf_start = _date.fromisoformat(etf_dates[-1]) if etf_dates else today - _td(days=365)

                def _etf_chunk(cur: int, tot: int) -> None:
                    emit("sync_index", 88, f"ETF 日K批次 {cur}/{tot}",
                         stage_pct=int(100 * cur / tot) if tot else 100, skip_log=cur < tot)

                written_etf_daily = index_sync.sync_and_persist_etf_daily(
                    repo,
                    capset,
                    start_date=_dt.combine(etf_start, _dt.min.time()),
                    end_date=_dt.combine(today, _dt.min.time()),
                    on_chunk_done=_etf_chunk,
                )
                emit("sync_index", 88, f"ETF 日K完成,{written_etf_daily} 行")
                _invalidate("etf_instruments")
                _invalidate("etf_daily")

            repo.refresh_index_views()
            emit(
                "sync_index",
                89,
                f"同步完成,指数 {index_count} 只/{written_index_daily} 行, ETF {etf_count} 只/{written_etf_daily} 行"
                + (f", ETF复权 {etf_adj_symbols} 只" if etf_adj_symbols else ""),
            )
        except Exception as e:  # noqa: BLE001
            logger.warning("sync_index/etf failed: %s", e)
            emit("sync_index", 89, f"指数/ETF同步失败:{e}")
            stage_errors.append(f"index/etf sync: {e}")
    else:
        skipped.append("sync_index")

    # 无 KLINE_DAILY_BATCH 能力时，上面的权威指数同步会被跳过，但盘后
    # 看板仍必须能拿到当天的指数快照。付费分支若已补齐今天，这里会因
    # 分区日期检查直接返回，不会重复请求。
    if pull_index and not capset.has(Cap.KLINE_DAILY_BATCH):
        written_index_daily += _gap_fill_index_snapshot(
            repo,
            today,
            now,
            pull_index=pull_index,
            emit=emit,
            stage_errors=stage_errors,
        )

    # Step 2.5: 分钟 K 同步(可选) — 未启用或无 capability 时静默跳过(不 emit)
    from app.services import preferences
    minute_on = preferences.get_minute_sync_enabled()
    minute_days = preferences.get_minute_sync_days()
    written_minute = 0
    if minute_on and capset.has(Cap.KLINE_MINUTE_BATCH):
        minute_start = today - _td(days=minute_days)
        emit("sync_minute", 90, f"获取分钟K [{minute_start} ~ {today}]…")
        logger.info("sync_minute: [%s ~ %s] start", minute_start, today)
        minute_symbols = _resolve_minute_symbols(capset, repo)
        def _minute_chunk_progress(cur: int, tot: int, seg_label: str = "") -> None:
            emit("sync_minute", 90 + int(3 * cur / tot),
                 f"分钟K 批次 {cur}/{tot}" + (f" [{seg_label}]" if seg_label else ""),
                 stage_pct=int(100 * cur / tot), skip_log=True)
        written_minute = kline_sync.sync_and_persist_minute(
            minute_symbols, repo, capset, days=minute_days,
            on_chunk_done=_minute_chunk_progress,
        )
        minute_dir = repo.store.data_dir / "kline_minute"
        minute_cover_days = len(list(minute_dir.glob("date=*"))) if minute_dir.exists() else 0
        emit("sync_minute", 93, f"分钟K完成,覆盖 {minute_cover_days} 天")
        logger.info("sync_minute: [%s ~ %s] done, %d days", minute_start, today, minute_cover_days)
        _invalidate("minute")
    else:
        skipped.append("sync_minute")
        if minute_on:
            logger.info("sync_minute skipped: no KLINE_MINUTE_BATCH capability")
        else:
            logger.info("sync_minute skipped: user disabled")

    # Step 2.6: 市场环境(regime) 增量计算 — enriched 已就绪后聚合环境指标。
    # 双检测(缺口+stale), 自动补算遗漏/被覆写的日。软失败: 不阻断主管道。
    # 默认关闭: regime 是本地聚合计算(非拉取), 首次/regime 表为空时需全量回填
    # 多日, 内存与耗时较高。用户可在数据页「市场环境」卡片设置里开启自动计算,
    # 或直接在该页面点「重算」手动触发(不受此开关影响)。
    regime_days = 0
    from app.services import preferences as _prefs_regime
    if not _prefs_regime.get_pipeline_regime_enabled():
        skipped.append("regime")
        logger.info("compute_regime skipped: user disabled (pipeline_regime_enabled=False)")
    else:
        try:
            emit("compute_regime", 90, "计算市场环境…")
            from app.services import regime_builder
            from app.api.regime import invalidate_regime_cache
            new_regime = regime_builder.compute_regime_incremental(repo, repo.store.data_dir)
            regime_days = new_regime.height if not new_regime.is_empty() else 0
            if regime_days:
                invalidate_regime_cache()
                logger.info("compute_regime: %d days", regime_days)
            emit("compute_regime", 92, f"市场环境 {regime_days} 天")
        except Exception as e:  # noqa: BLE001
            logger.warning("compute_regime failed (soft): %s", e)
            stage_errors.append(f"compute_regime: {e}")
            skipped.append("regime")

    # Step 3: 刷新视图
    emit("refresh_views", 95, "刷新 DuckDB 视图…")
    _refresh_views(repo)

    emit("done", 100, "完成")
    _invalidate(None)  # 兜底:全清

    result = {
        "universe_size": len(universe),
        "daily_days": new_daily_days,
        "adj_factor_symbols": len(affected_symbols),
        "enriched_days": written_enriched,
        "index_count": index_count,
        "index_daily_rows": written_index_daily,
        "etf_count": etf_count,
        "etf_daily_rows": written_etf_daily,
        "etf_adj_factor_symbols": etf_adj_symbols,
        "minute_rows": written_minute,
        "regime_days": regime_days,
        "lagging_symbols": len(lagging_symbols),
        "skipped_stages": skipped,
        "stage_errors": stage_errors,
    }

    freshness_report: dict | None = None
    if pull_a_share:
        target_snapshot_date = required_market_snapshot_date(now, _prefs.get_pipeline_schedule())
        freshness_errors = validate_market_snapshot_freshness(
            repo,
            target_snapshot_date,
            require_enriched=True,
        )
        freshness_report = (
            _provider_snapshot_coverage(repo, target_snapshot_date, universe)
            if freshness_errors
            else _persisted_snapshot_coverage(repo, target_snapshot_date, universe)
        )
        result["data_freshness"] = freshness_report
        if freshness_errors:
            stage_errors.extend(freshness_errors)
            result["stage_errors"] = stage_errors
            result["data_freshness"] = freshness_report

    # 有阶段软失败: 进度协议已走完(done/100, 前端进度条正常收尾), 但数据可能陈旧,
    # 抛出让上层 job_store 把终态标记为 failed —— 不再"部分失败却报成功"。
    if stage_errors:
        raise PipelineStageError(stage_errors, data_freshness=freshness_report)

    return result


def _refresh_views(repo: KlineRepository) -> None:
    """刷新所有 DuckDB 视图 —— 委托给 repository 的唯一权威实现 rebuild_views()。"""
    repo.rebuild_views()


def _refresh_single_view(repo: KlineRepository, name: str) -> None:
    """刷新单个 DuckDB 视图。"""
    d = repo.store.data_dir.as_posix()
    paths = {
        "kline_daily": f"{d}/kline_daily/**/*.parquet",
        "kline_enriched": f"{d}/kline_daily_enriched/**/*.parquet",
        "kline_index_daily": f"{d}/kline_index_daily/**/*.parquet",
        "kline_index_enriched": f"{d}/kline_index_enriched/**/*.parquet",
        "kline_etf_daily": f"{d}/kline_etf_daily/**/*.parquet",
        "kline_etf_enriched": f"{d}/kline_etf_enriched/**/*.parquet",
        "kline_etf_minute": f"{d}/kline_etf_minute/**/*.parquet",
        "kline_minute": f"{d}/kline_minute/**/*.parquet",
        "adj_factor": f"{d}/adj_factor/**/*.parquet",
        "adj_factor_etf": f"{d}/adj_factor_etf/**/*.parquet",
        "instruments": f"{d}/instruments/**/*.parquet",
        "instruments_index": f"{d}/instruments_index/**/*.parquet",
        "instruments_etf": f"{d}/instruments_etf/**/*.parquet",
    }
    path = paths.get(name)
    if not path:
        return
    try:
        repo.db.execute(
            f"CREATE OR REPLACE VIEW {name} AS "
            f"SELECT * FROM read_parquet('{path}', union_by_name=true)"
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("refresh view %s failed: %s", name, e)


def _resolve_minute_symbols(capset: CapabilitySet, repo=None) -> list[str]:
    """分钟 K 同步标的 — 与日K共用同一标的池。"""
    return _resolve_universe(capset, repo)


def _refresh_instruments_view(repo: KlineRepository) -> None:
    """单独刷新 instruments 视图。"""
    d = repo.store.data_dir.as_posix()
    try:
        repo.db.execute(
            f"CREATE OR REPLACE VIEW instruments AS "
            f"SELECT * FROM read_parquet('{d}/instruments/**/*.parquet', union_by_name=true)"
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("refresh instruments view failed: %s", e)


def _run_tracked(fn, job_label: str) -> None:
    """调度触发时包装 JobStore 跟踪，确保同步历史有记录。

    单飞: 若已有活跃(pending∨running)任务(手动同步中), 本次调度直接跳过, 不并发。
    重任务执行槽: 再挡一层僵尸并发(reap 后线程仍活时不得并行写 parquet)。
    """
    from app.services.pipeline_jobs import job_store, release_run_slot, try_acquire_run_slot

    job_id, is_new = job_store.create()
    if not is_new:
        logger.info("scheduled %s 跳过: 已有活跃任务在运行 (job_id=%s)", job_label, job_id)
        return
    if not try_acquire_run_slot():
        logger.warning("scheduled %s 跳过: 重任务执行槽被占用(疑似上次任务卡死)", job_label)
        job_store.fail(job_id, f"scheduled {job_label} skipped: 已有数据任务在运行")
        return

    def progress(stage: str, pct: int, msg: str, stage_pct: int | None = None,
                 skip_log: bool = False) -> None:
        job_store.progress(job_id, stage, pct, msg, stage_pct=stage_pct, skip_log=skip_log)

    try:
        job_store.start(job_id)
        result = fn(on_progress=progress)
        job_store.succeed(job_id, result)
        logger.info("scheduled %s completed: job_id=%s", job_label, job_id)
    except Exception as exc:
        logger.exception("scheduled %s failed: job_id=%s", job_label, job_id)
        job_store.fail(
            job_id,
            f"scheduled {job_label} failed: {exc}",
            details=pipeline_error_details(exc),
        )
    finally:
        release_run_slot()


# ================================================================
# 定时复盘 (AI 大盘复盘报告)
# ================================================================

REVIEW_JOB_ID_PREFIX = "scheduled_review"


def review_job_id(user_id: str) -> str:
    """Return the durable scheduler key for one account's private review."""
    return f"{REVIEW_JOB_ID_PREFIX}:{user_id}"


async def _run_scheduled_review(repo, user, user_root: Path) -> None:
    """Run a review with the owning account bound for its whole lifetime."""
    from app.services.user_context import reset_current_user, set_current_user

    tokens = set_current_user(user, user_root)
    try:
        await _run_scheduled_review_in_context(repo, user.id)
    finally:
        reset_current_user(tokens)


async def _run_scheduled_review_in_context(repo, owner_id: str) -> None:
    """定时复盘 job: 流式生成复盘 → 实时推 SSE(开着页面可见) → 落盘归档 → 推飞书。

    与手动「生成复盘」体验一致: 流式事件经 quote_service.push_review_event →
    /api/intraday/stream 的 review_progress 事件 → 前端 reviewStore, 用户开着复盘页
    即可看到报告边生成边显示, 切走再回来也能看到生成中/已生成。
    LLM 偶发断流(peer closed connection)时自动重试最多 2 次。
    任何异常都吞掉只记日志, 绝不影响调度器主循环。
    """
    import json

    try:
        from app.services import market_recap_reports
        from app.services.ai_provider import ai_configured

        # AI Key 未配置时跳过(避免每日报错刷日志)
        if not ai_configured():
            logger.info("scheduled review skipped: AI key not configured")
            return

        app_state = _get_app_state()
        quote_service = getattr(app_state, "quote_service", None) if app_state else None
        depth_service = getattr(app_state, "depth_service", None) if app_state else None

        content, meta = await _stream_review_with_retry(repo, quote_service, depth_service, owner_id)
        if not content:
            logger.warning("scheduled review produced no content (meta=%s)", meta)
            # 通知前端进入 error 态(若有页面在听)
            if quote_service:
                quote_service.push_review_event(
                    json.dumps({"type": "error", "message": "复盘生成失败,请稍后手动重试"}, ensure_ascii=False),
                    owner_id=owner_id,
                )
            return

        # 落盘: 与手动生成完全相同的归档格式
        market_recap_reports.save_report({
            "as_of": meta.get("as_of"),
            "focus": "",
            "content": content,
            "summary": meta.get("summary", ""),
            "emotion_score": meta.get("emotion_score"),
            "emotion_label": meta.get("emotion_label", ""),
        })
        logger.info("scheduled review saved: as_of=%s", meta.get("as_of"))

        # 通知前端: 生成完成且已归档(archived=true 让前端只刷新列表, 不重复归档)
        if quote_service:
            quote_service.push_review_event(
                json.dumps({"type": "done", "archived": True}, ensure_ascii=False),
                owner_id=owner_id,
            )

        # 推送到飞书(可选): 运行时读取配置, 用户改设置下次触发即生效。
        # 失败静默降级, 不影响已归档的报告。
        _maybe_push_review(content, meta)
    except Exception as e:  # noqa: BLE001
        logger.exception("scheduled review failed: %s", e)
        # 兜底: 异常时通知前端停止「生成中」状态, 避免页面卡在 streaming
        try:
            app_state = _get_app_state()
            qs = getattr(app_state, "quote_service", None) if app_state else None
            if qs:
                import json as _json
                qs.push_review_event(
                    _json.dumps({"type": "error", "message": "复盘生成异常,请稍后手动重试"}, ensure_ascii=False),
                    owner_id=owner_id,
                )
        except Exception:  # noqa: BLE001
            pass


async def _stream_review_with_retry(repo, quote_service, depth_service, owner_id: str) -> tuple[str, dict]:
    """流式生成复盘, 每个事件推 SSE + 累积内容。LLM 断流时最多重试 2 次。

    返回 (content, meta)。重试时推一个 retry 事件让前端清空已累积内容重新开始。
    成功(收到 done/无 error)或耗尽重试后返回。
    """
    import asyncio
    import json
    from app.services.market_recap import recap_market_stream

    max_attempts = 3  # 初次 + 2 次重试
    last_meta: dict = {}
    content_parts: list[str] = []

    for attempt in range(1, max_attempts + 1):
        content_parts = []  # 每次重试重新累积
        failed = False
        try:
            async for evt_json in recap_market_stream(repo, quote_service, depth_service):
                evt = json.loads(evt_json)
                t = evt.get("type")

                # 推给前端(让开着页面的用户实时看到, 与手动一致)
                if quote_service:
                    quote_service.push_review_event(evt_json, owner_id=owner_id)

                if t == "meta":
                    last_meta = evt
                elif t == "delta" and evt.get("content"):
                    content_parts.append(evt["content"])
                elif t == "error":
                    failed = True
                    logger.warning("scheduled review stream error (attempt %d/%d): %s",
                                   attempt, max_attempts, evt.get("message"))
                    break  # 触发重试
                elif t == "done":
                    # provider 在输出预算耗尽且补齐次数用尽时会明确标记
                    # complete=false;不能把半截复盘归档成成功,交给现有重试路径。
                    if evt.get("complete", True) is False:
                        failed = True
                        logger.warning(
                            "scheduled review stream incomplete (attempt %d/%d): finish_reason=%s",
                            attempt, max_attempts, evt.get("finish_reason"),
                        )
                        break
                    return "".join(content_parts), last_meta
            # 流自然结束(无 done 事件)且有内容, 视为成功
            if content_parts and not failed:
                return "".join(content_parts), last_meta
        except Exception as e:  # noqa: BLE001
            # LLM 断流等异常(httpx.RemoteProtocolError)落到这里
            failed = True
            logger.warning("scheduled review stream exception (attempt %d/%d): %s",
                           attempt, max_attempts, e)

        # 失败: 决定是否重试
        if attempt < max_attempts:
            logger.info("scheduled review retrying in 3s (attempt %d → %d)", attempt, attempt + 1)
            # 通知前端: 即将重试, 清空已累积内容重新开始
            if quote_service:
                quote_service.push_review_event(
                    json.dumps({"type": "retry", "attempt": attempt + 1}, ensure_ascii=False),
                    owner_id=owner_id,
                )
            await asyncio.sleep(3)

    # 耗尽重试, 返回已累积内容(可能为空)和最后 meta
    return "".join(content_parts), last_meta


def _maybe_push_review(content: str, meta: dict) -> None:
    """复盘报告归档后, 按 review_push_channels 选定的外部工具逐个推送完整报告。

    定时生成与手动生成共用本函数 (手动归档端点 POST /api/market-recap/reports 也会调用)。
    channels 为空则不推送; 'feishu' 复用监控中心的全局飞书 Webhook 通道。
    推送失败静默降级 (Webhook 是辅助通道), 不影响已归档的报告。
    """
    try:
        from app.services import preferences, webhook_adapter

        channels = preferences.get_review_push_channels()
        if not channels:
            return

        emotion = f"{meta.get('emotion_label') or ''}".strip()
        as_of = meta.get("as_of") or ""
        subtitle = as_of + (f" · 情绪 {emotion}" if emotion else "")

        for ch in channels:
            if ch == "feishu":
                url = preferences.get_feishu_webhook_url()
                if not url:
                    logger.info("review push(feishu) skipped: webhook not configured")
                    continue
                secret = preferences.get_feishu_webhook_secret()
                ok = webhook_adapter.send_feishu_card(
                    url, "每日复盘", subtitle, content, secret
                )
                logger.info("review push(feishu) %s", "sent" if ok else "failed")
            elif ch == "wecom":
                url = preferences.get_wecom_webhook_url()
                if not url:
                    logger.info("review push(wecom) skipped: webhook not configured")
                    continue
                # 企业微信 markdown 标题已含一级标题, subtitle 拼到正文首行
                full_body = (f"**{subtitle}**\n\n{content}" if subtitle else content)
                ok = webhook_adapter.send_wecom_markdown(
                    url, "每日复盘", full_body
                )
                logger.info("review push(wecom) %s", "sent" if ok else "failed")
            # 未来更多渠道在此追加分支
    except Exception as e:  # noqa: BLE001
        logger.warning("review push error: %s", e)


def _register_review_job(scheduler, repo, user, user_root: Path, hour: int, minute: int) -> None:
    """注册/更新定时复盘 job(工作日 mon-fri, Asia/Shanghai)。

    供 start_scheduler(启动时) 和 settings API(改时间时) 共用。
    用 replace_existing=True, 重复注册只更新 trigger。

    注意: _run_scheduled_review 是协程函数, 必须把函数对象本身(配合 args)传给
    add_job, 而非用 lambda 包裹 —— 否则 APScheduler 会把 lambda 当同步函数在线程池
    执行, 仅得到一个未 await 的协程对象, 复盘实际不会运行。
    """
    scheduler.add_job(
        _run_scheduled_review,
        args=[repo, user, user_root],
        trigger=CronTrigger(day_of_week="mon-fri",
                            hour=hour, minute=minute,
                            timezone="Asia/Shanghai"),
        id=review_job_id(user.id),
        misfire_grace_time=7200,  # 复盘非关键, 允许 2 小时内补跑
        replace_existing=True,
    )


def _register_persisted_review_jobs(scheduler, repo) -> int:
    """Restore enabled private review jobs after a server restart."""
    from app.services import preferences
    from app.services.account_store import get_account_store
    from app.services.user_context import reset_current_user, set_current_user

    store = get_account_store(settings.data_dir)
    registered = 0
    for user in store.list_active_identities():
        user_root = store.ensure_workspace(user.id)
        tokens = set_current_user(user, user_root)
        try:
            schedule = preferences.get_review_schedule()
        finally:
            reset_current_user(tokens)
        if not schedule["enabled"]:
            continue
        _register_review_job(scheduler, repo, user, user_root, schedule["hour"], schedule["minute"])
        registered += 1
    return registered


def start_scheduler(repo: KlineRepository, capset: CapabilitySet) -> AsyncIOScheduler:
    """启动调度器。

    工作日 09:10 — 同步个股维表
    工作日 HH:MM — 盘后管道（时间由用户偏好决定，默认 15:30）
    """
    from app.services import preferences
    sched = preferences.get_pipeline_schedule()
    inst_sched = preferences.get_instruments_schedule()

    scheduler = AsyncIOScheduler(timezone="Asia/Shanghai")

    # 盘前: 同步 instruments（时间由偏好决定）
    def _instruments_task(on_progress=None):
        emit = on_progress or _noop
        emit("sync_instruments", 0, "同步个股维表…")
        result = run_instruments_sync(repo)
        emit("done", 100, f"个股维表同步完成,{result.get('instruments_rows', 0)} 只标的")
        return result

    scheduler.add_job(
        lambda: _run_tracked(_instruments_task, "instruments_sync"),
        trigger=CronTrigger(day_of_week="mon-fri",
                            hour=inst_sched["hour"], minute=inst_sched["minute"],
                            timezone="Asia/Shanghai"),
        id="pre_market_instruments",
        misfire_grace_time=1800,
        replace_existing=True,
    )

    # 盘后: 日 K + enriched（时间由偏好决定）
    def _pipeline_then_refresh(on_progress=None):
        # 与手动触发 (/api/pipeline/run) 对齐: 管道落盘后重建 Polars 内存缓存,
        # 否则 live_agg 的昨日连板数等基准列会停留在旧交易日, 次日开盘连板梯队
        # 整体少算一档 (仅手动触发或重启才会刷缓存, cron 调度路径此前漏了这步)。
        # 用 app.state 上的**实时** capset(周期重探会热更新它), 而非启动时捕获的
        # 旧 capset —— 否则 Key 中途过期/续费后, 调度管道仍按旧档位打端点。
        app_state = _get_app_state()
        capset_live = getattr(app_state, "capabilities", None) or capset
        # 管道运行期间暂停实时行情取数, 防止覆写同一批 parquet 竞态
        qs = getattr(app_state, "quote_service", None)
        try:
            if qs:
                with qs.paused():
                    result = run_now(repo, capset_live, on_progress=on_progress)
            else:
                result = run_now(repo, capset_live, on_progress=on_progress)
        finally:
            # 即便有阶段软失败(run_now 末尾抛 PipelineStageError), 已落盘的日K/enriched
            # 仍需刷进内存缓存, 否则 live_agg 基准列停留在旧交易日。放 finally 保证部分
            # 成功也生效; 随后异常继续上抛, 由 _run_tracked 标记任务 failed。
            repo.refresh_cache()
        return result

    scheduler.add_job(
        lambda: _run_tracked(_pipeline_then_refresh, "daily_pipeline"),
        trigger=CronTrigger(day_of_week="mon-fri",
                            hour=sched["hour"], minute=sched["minute"],
                            timezone="Asia/Shanghai"),
        id="daily_pipeline",
        misfire_grace_time=3600,
        replace_existing=True,
    )

    def _pipeline_snapshot_ready() -> bool:
        target = required_market_snapshot_date(_datetime.now(BEIJING_TZ), sched)
        try:
            return _is_pipeline_snapshot_ready(
                repo,
                target,
                pull_index=_prefs.get_pipeline_pull_index(),
            )
        except Exception:
            return False

    def _provider_snapshot_ready_for_retry() -> bool:
        """Avoid a full retry while a custom provider has not published today."""
        if _prefs.get_daily_data_provider() == "tickflow":
            return True
        target = required_market_snapshot_date(_datetime.now(BEIJING_TZ), sched)
        try:
            from app.services.market_overview_builder import _dashboard_daily_snapshot

            provider_date, _ = _dashboard_daily_snapshot(repo)
            return bool(provider_date and provider_date >= target)
        except Exception:
            return False

    def _run_pipeline_attempt(label: str) -> None:
        if _pipeline_snapshot_ready():
            logger.info("scheduled %s skipped: current market snapshot is already persisted", label)
            return
        if not _provider_snapshot_ready_for_retry():
            logger.info("scheduled %s deferred: provider has not published the target daily snapshot", label)
            return
        _run_tracked(_pipeline_then_refresh, label)

    for retry_hour, retry_minute in post_close_retry_times(sched):
        retry_label = f"daily_pipeline_retry_{retry_hour:02d}{retry_minute:02d}"
        scheduler.add_job(
            lambda label=retry_label: _run_pipeline_attempt(label),
            trigger=CronTrigger(
                day_of_week="mon-fri",
                hour=retry_hour,
                minute=retry_minute,
                timezone="Asia/Shanghai",
            ),
            id=retry_label,
            misfire_grace_time=1800,
            replace_existing=True,
        )

    # 启动补跑: 服务器若错过了收盘管道及其重试 (宕机/部署重启), 启动 3 分钟后
    # 检查目标日快照; 未就绪则补跑一次, 避免数据停在旧交易日直到下一个 15:30。
    def _boot_catchup() -> None:
        if _pipeline_snapshot_ready():
            logger.info("boot catchup skipped: market snapshot already up to date")
            return
        if not _provider_snapshot_ready_for_retry():
            logger.info("boot catchup deferred: provider has not published the target snapshot")
            return
        logger.warning("boot catchup: market snapshot outdated, running pipeline now")
        _run_tracked(_pipeline_then_refresh, "boot_catchup")

    scheduler.add_job(
        _boot_catchup,
        trigger=DateTrigger(
            run_date=_datetime.now(BEIJING_TZ) + _timedelta(minutes=3),
        ),
        id="boot_catchup",
        replace_existing=True,
    )

    # 盘后: 五档盘口 sealed 定版(时间由偏好决定, 默认15:02, 范围15:01~18:00)
    depth_sched = preferences.get_depth_finalize_time()

    def _depth_finalize():
        depth_svc = getattr(_get_app_state(), "depth_service", None) if _get_app_state() else None
        if depth_svc:
            depth_svc.finalize()

    scheduler.add_job(
        _depth_finalize,
        trigger=CronTrigger(day_of_week="mon-fri",
                            hour=depth_sched["hour"], minute=depth_sched["minute"],
                            timezone="Asia/Shanghai"),
        id="depth_finalize",
        misfire_grace_time=3600,
        replace_existing=True,
    )

    # 周期性能力重探: 付费 Key 中途过期/续费无需重启即可被发现。
    # 只热更新 app.state.capabilities(API 端点、盘后管道 _pipeline_then_refresh 均读它);
    # 档位变化记 WARNING, 让「Key 失效」在日志/前端可见, 不再静默按旧档位打 403 端点。
    def _reprobe_capabilities():
        from app.tickflow.policy import detect_capabilities, tier_label
        app_state = _get_app_state()
        if app_state is None:
            return
        try:
            old = getattr(app_state, "capabilities", None)
            old_n = len(old.all()) if old else -1
            new_capset = detect_capabilities(force=True)
            app_state.capabilities = new_capset
            new_n = len(new_capset.all())
            if old_n != new_n:
                logger.warning(
                    "能力集变化: %d → %d capabilities (档位=%s)。Key 过期/续费或端点波动, "
                    "已热更新 app.state.capabilities。", old_n, new_n, tier_label(),
                )
        except Exception as e:  # noqa: BLE001
            logger.warning("周期能力重探失败(保留现有能力集): %s", e)

    scheduler.add_job(
        _reprobe_capabilities,
        trigger=IntervalTrigger(minutes=60),
        id="reprobe_capabilities",
        misfire_grace_time=600,
        replace_existing=True,
    )

    # 定时复盘 (AI 大盘复盘报告): 工作日到点自动生成并归档。
    # 默认关闭 —— 仅当用户在复盘页开启时才注册 job。
    # 复用 recap_market_once(非流式) + market_recap_reports.save_report(落盘)。
    # quote_service / depth_service 通过 _get_app_state() 延迟取用。
    review_job_count = _register_persisted_review_jobs(scheduler, repo)
    if review_job_count:
        logger.info("restored %d owner-scoped scheduled review jobs", review_job_count)

    # 通用页面预热: 启动 4 分钟后 + 工作日 9:05/16:05 各跑一次。
    # 9:05 覆盖盘中实时列场景; 16:05 在盘后管道(默认15:30)落盘后重建当日缓存键,
    # 保证次日开盘前 RPS 矩阵已是新数据。幂等, 命中缓存时秒回。
    def _page_prewarm_job(on_progress=None) -> None:
        app_state = _get_app_state()
        repo_live = getattr(app_state, "repo", None) if app_state else None
        qs = getattr(app_state, "quote_service", None) if app_state else None
        from app.services.page_prewarm import prewarm_common_pages
        prewarm_common_pages(repo_live or repo, qs)

    scheduler.add_job(
        lambda: _run_tracked(_page_prewarm_job, "page_prewarm_boot"),
        trigger=DateTrigger(
            run_date=_datetime.now(BEIJING_TZ) + _timedelta(minutes=4),
        ),
        id="page_prewarm_boot",
        replace_existing=True,
    )
    scheduler.add_job(
        lambda: _run_tracked(_page_prewarm_job, "page_prewarm"),
        trigger=CronTrigger(day_of_week="mon-fri",
                            hour="9,16", minute=5,
                            timezone="Asia/Shanghai"),
        id="page_prewarm",
        misfire_grace_time=1800,
        replace_existing=True,
    )

    scheduler.start()
    logger.info("scheduler started; instruments@%02d:%02d, pipeline@%02d:%02d, depth@%02d:%02d mon-fri",
                inst_sched["hour"], inst_sched["minute"], sched["hour"], sched["minute"],
                depth_sched["hour"], depth_sched["minute"])
    return scheduler


# app_state 延迟引用(start_scheduler 在 lifespan 早期调用, app.state 可能还没就绪)
_app_state_ref = None


def set_app_state(app_state) -> None:
    """lifespan 注册 app.state 引用, 供 scheduled job 访问 depth_service 等单例。"""
    global _app_state_ref
    _app_state_ref = app_state


def _get_app_state():
    return _app_state_ref
