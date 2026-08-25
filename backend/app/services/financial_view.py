"""Read-side financial data contract for the financial analysis page."""
from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

import polars as pl

from app.data_providers import custom as custom_sources
from app.services import preferences
from app.services.financial_sync import get_financial_df

logger = logging.getLogger(__name__)


_ALIASES: dict[str, dict[str, str]] = {
    "income": {
        "end_date": "period_end",
        "ann_date": "announce_date",
        "oper_cost": "operating_cost",
        "operate_profit": "operating_profit",
        "sell_exp": "selling_expense",
        "admin_exp": "admin_expense",
        "rd_exp": "rd_expense",
        "fin_exp": "financial_expense",
        "non_oper_income": "non_operating_income",
        "non_oper_exp": "non_operating_expense",
        "n_income": "net_income",
        "n_income_attr_p": "net_income_attributable",
        "basic_eps": "basic_eps",
        "diluted_eps": "diluted_eps",
    },
    "balance_sheet": {
        "end_date": "period_end",
        "ann_date": "announce_date",
        "total_cur_assets": "total_current_assets",
        "total_nca": "total_non_current_assets",
        "money_cap": "cash_and_equivalents",
        "accounts_receiv": "accounts_receivable",
        "inventories": "inventory",
        "fix_assets": "fixed_assets",
        "intan_assets": "intangible_assets",
        "total_cur_liab": "total_current_liabilities",
        "total_ncl": "total_non_current_liabilities",
        "st_borr": "short_term_borrowing",
        "lt_borr": "long_term_borrowing",
        "acct_payable": "accounts_payable",
        "total_hldr_eqy_inc_min_int": "total_equity",
        "total_hldr_eqy_exc_min_int": "equity_attributable",
        "retained_earnings": "retained_earnings",
        "minority_int": "minority_interest",
    },
    "cash_flow": {
        "end_date": "period_end",
        "ann_date": "announce_date",
        "n_cashflow_act": "net_operating_cash_flow",
        "n_cashflow_inv_act": "net_investing_cash_flow",
        "n_cash_flows_fnc_act": "net_financing_cash_flow",
        "c_pay_acq_const_fiolta": "capex",
        "n_incr_cash_cash_equ": "net_cash_change",
    },
    "shares": {
        "period_end": "period_end",
        "announce_date": "announce_date",
    },
}


def _alias_if_missing(frame: pl.DataFrame, source: str, target: str) -> pl.DataFrame:
    if target in frame.columns or source not in frame.columns:
        return frame
    return frame.with_columns(pl.col(source).alias(target))


def normalize_financial_frame(table: str, frame: pl.DataFrame) -> pl.DataFrame:
    """Add the stable fields consumed by the UI without dropping provider fields.

    TeaJoin exposes Tushare-compatible names. The stored parquet remains raw for
    compatibility; this read-side adapter supplies canonical aliases and applies
    the documented daily_basic 万元→元 market-value conversion.
    """
    if frame.is_empty():
        return frame

    out = frame
    if "ts_code" in out.columns and "symbol" not in out.columns:
        out = out.rename({"ts_code": "symbol"})

    if table == "metrics":
        out = _alias_if_missing(out, "trade_date", "period_end")
        out = _alias_if_missing(out, "trade_date", "announce_date")
        for source, target in (("total_mv", "market_cap"), ("circ_mv", "float_market_cap")):
            if target not in out.columns and source in out.columns:
                out = out.with_columns(
                    (pl.col(source).cast(pl.Float64, strict=False) * 10_000.0).alias(target)
                )
    else:
        for source, target in _ALIASES.get(table, {}).items():
            out = _alias_if_missing(out, source, target)
    return out


def prepare_financial_prompt_frame(table: str, frame: pl.DataFrame) -> pl.DataFrame:
    """Return an AI-safe financial view with explicit canonical units.

    Raw daily-basic names such as ``total_mv`` (万元), ``total_share``
    (万股) and ``turnover_rate`` (百分比) are removed after canonical aliases
    are materialized, preventing unit ambiguity inside the prompt.
    """
    out = normalize_financial_frame(table, frame)
    if out.is_empty() or table != "metrics":
        return out
    expressions = []
    if "market_cap" in out.columns:
        expressions.append(pl.col("market_cap").cast(pl.Float64, strict=False).alias("market_cap_cny"))
    elif "total_mv" in out.columns:
        expressions.append(
            (pl.col("total_mv").cast(pl.Float64, strict=False) * 10_000.0).alias("market_cap_cny")
        )
    if "float_market_cap" in out.columns:
        expressions.append(
            pl.col("float_market_cap").cast(pl.Float64, strict=False).alias("float_market_cap_cny")
        )
    elif "circ_mv" in out.columns:
        expressions.append(
            (pl.col("circ_mv").cast(pl.Float64, strict=False) * 10_000.0).alias("float_market_cap_cny")
        )
    if "total_share" in out.columns:
        expressions.append(
            (pl.col("total_share").cast(pl.Float64, strict=False) * 10_000.0).alias("total_shares")
        )
    if "float_share" in out.columns:
        expressions.append(
            (pl.col("float_share").cast(pl.Float64, strict=False) * 10_000.0).alias("float_shares")
        )
    if "turnover_rate" in out.columns:
        expressions.append(
            pl.col("turnover_rate").cast(pl.Float64, strict=False).alias("turnover_rate_pct")
        )
    if expressions:
        out = out.with_columns(expressions)
    drop = [
        column for column in (
            "total_mv", "circ_mv", "total_share", "float_share", "turnover_rate",
            "market_cap", "float_market_cap",
        )
        if column in out.columns
    ]
    return out.drop(drop) if drop else out


def _custom_financial_provider() -> Any | None:
    provider_name = preferences.get_financial_provider()
    if not custom_sources.is_custom_provider(provider_name):
        return None
    if not custom_sources.provider_has_dataset(provider_name, "financial"):
        return None
    return custom_sources.get_provider(provider_name)


def load_financial_frame(
    data_dir: Path,
    table: str,
    symbol: str,
    *,
    latest_only: bool = True,
    provider_factory: Callable[[], Any | None] | None = None,
) -> pl.DataFrame:
    """Load one symbol, using TeaJoin only when the local table misses it."""
    normalized_symbol = symbol.strip().upper()
    local = get_financial_df(data_dir, table)
    if not local.is_empty() and "symbol" in local.columns:
        local = local.filter(pl.col("symbol").cast(pl.Utf8) == normalized_symbol)
        if not local.is_empty():
            return normalize_financial_frame(table, local)

    owns_provider = provider_factory is not None
    try:
        provider = (provider_factory or _custom_financial_provider)()
        if provider is None:
            return normalize_financial_frame(table, local)
        fetched = provider.get_financials(table, [normalized_symbol], latest_only=latest_only)
        return normalize_financial_frame(table, fetched)
    except Exception as exc:
        logger.warning("financial read fallback failed for %s/%s: %s", table, normalized_symbol, exc)
        return normalize_financial_frame(table, local)
    finally:
        # A factory creates a request-scoped provider. The default loader returns
        # a process-wide provider shared by daily, realtime and financial calls;
        # closing it here would make later market-data requests fail with
        # "client has been closed" until the whole source registry is reloaded.
        if owns_provider and "provider" in locals() and provider is not None:
            close = getattr(provider, "close", None)
            if callable(close):
                close()


def _local_search(repo: Any, keyword: str, limit: int) -> list[dict]:
    frame = repo.get_instruments_asset("stock")
    if frame.is_empty() or "symbol" not in frame.columns:
        return []
    columns = [col for col in ("symbol", "name", "code") if col in frame.columns]
    frame = frame.select(columns)
    keyword_upper = keyword.upper()
    masks = [pl.col("symbol").cast(pl.Utf8).str.to_uppercase().str.contains(keyword_upper, literal=True)]
    if "code" in frame.columns:
        masks.append(pl.col("code").cast(pl.Utf8).str.contains(keyword_upper, literal=True))
    if "name" in frame.columns:
        masks.append(pl.col("name").cast(pl.Utf8).str.contains(keyword, literal=True))
    mask = masks[0]
    for other in masks[1:]:
        mask = mask | other
    rows = frame.filter(mask).head(limit).to_dicts()
    return [
        {"symbol": str(row.get("symbol") or ""), "name": str(row.get("name") or ""),
         "code": str(row.get("code") or str(row.get("symbol") or "").split(".", 1)[0]),
         "asset_type": "stock"}
        for row in rows
    ]


def _fetch_custom_instruments() -> pl.DataFrame:
    """Fetch the shared custom provider's stock universe without closing it."""
    provider = _custom_financial_provider()
    if provider is None:
        return pl.DataFrame()
    return provider.get_instruments("stock")


def search_financial_symbols(
    repo: Any,
    keyword: str,
    limit: int = 20,
    *,
    instruments_factory: Callable[[], pl.DataFrame] | None = None,
) -> list[dict]:
    """Search local instruments, then TeaJoin instruments when local misses."""
    q = keyword.strip()
    if not q:
        return []
    local = _local_search(repo, q, limit)
    if local:
        return local
    if len(q) < 2:
        return []
    try:
        frame = (instruments_factory or _fetch_custom_instruments)()
        if frame.is_empty():
            return []
        # The provider normalizer already supplies symbol/name/code.
        rows = frame.to_dicts()
        q_upper = q.upper()
        matched = [
            row for row in rows
            if q_upper in str(row.get("symbol") or "").upper()
            or q_upper in str(row.get("code") or "").upper()
            or q in str(row.get("name") or "")
        ][:limit]
        return [
            {"symbol": str(row.get("symbol") or ""), "name": str(row.get("name") or ""),
             "code": str(row.get("code") or str(row.get("symbol") or "").split(".", 1)[0]),
             "asset_type": "stock"}
            for row in matched if row.get("symbol")
        ]
    except Exception as exc:
        logger.warning("financial instrument search fallback failed for %s: %s", q, exc)
        return []
