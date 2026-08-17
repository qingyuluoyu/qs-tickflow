"""Tool definitions and execution for the Ask AI assistant.

The tool layer is deliberately small and boring: every handler reads through
the target repository/services, returns JSON-safe data, and never raises into
the model loop.  Unsupported source datasets remain explicit placeholders so
the assistant cannot hallucinate a result for them.
"""
from __future__ import annotations

import json
import logging
from datetime import date, timedelta
from typing import Any

import polars as pl

from app.services.debate import _concept_rows, _json_safe, _quote, normalize_symbol
from app.services.financial_sync import get_financial_df

logger = logging.getLogger(__name__)


def _tool(name: str, description: str, properties: dict[str, Any] | None = None, required: list[str] | None = None) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties or {},
                "required": required or [],
                "additionalProperties": False,
            },
        },
    }


_CODE = {"type": "string", "description": "股票代码，可为 600519 或 600519.SH"}
_TOOLS_WITH_DATA = {
    "query_quote", "query_valuation", "query_kline", "query_financials", "query_company_info",
    "query_concepts", "query_market", "query_industry_comparison", "query_lockup",
}

TOOLS: list[dict[str, Any]] = [
    _tool("query_quote", "查询标的最新可用行情（实时缓存优先，日线回退）。", {"code": _CODE}, ["code"]),
    _tool("query_valuation", "查询估值字段；当前仅部分行情源提供 PE/PB/市值。", {"code": _CODE}, ["code"]),
    _tool("query_valuation_percentile", "查询估值历史分位。", {"code": _CODE}, ["code"]),
    _tool("query_kline", "查询标的最近日 K 线及已计算指标。", {"code": _CODE, "days": {"type": "integer", "minimum": 1, "maximum": 250}}, ["code"]),
    _tool("query_financials", "查询目标项目已同步的核心财务表。", {"code": _CODE, "table": {"type": "string", "enum": ["metrics", "income", "cash_flow", "balance", "shares"]}}, ["code"]),
    _tool("query_company_info", "查询标的名称及基础证券信息。", {"code": _CODE}, ["code"]),
    _tool("query_reports", "查询近期研报。", {"code": _CODE}, ["code"]),
    _tool("query_news", "查询个股新闻。", {"code": _CODE}, ["code"]),
    _tool("query_fund_flow", "查询个股资金流向。", {"code": _CODE}, ["code"]),
    _tool("query_margin", "查询融资融券数据。", {"code": _CODE}, ["code"]),
    _tool("query_holders", "查询股东户数。", {"code": _CODE}, ["code"]),
    _tool("query_block_trade", "查询大宗交易。", {"code": _CODE}, ["code"]),
    _tool("query_dragon_tiger", "查询龙虎榜。", {"code": _CODE}, ["code"]),
    _tool("query_dividend", "查询分红数据。", {"code": _CODE}, ["code"]),
    _tool("query_announcements", "查询公司公告。", {"code": _CODE}, ["code"]),
    _tool("query_lockup", "查询限售解禁日历。", {"code": _CODE}, ["code"]),
    _tool("query_investor_qa", "查询投资者问答。", {"code": _CODE}, ["code"]),
    _tool("query_concepts", "查询目标项目 ext_data 中的概念和行业标签。", {"code": _CODE}, ["code"]),
    _tool("query_industry_comparison", "查询目标项目可用的行业/概念板块目录。", {"code": _CODE}, ["code"]),
    _tool("query_industry_reports", "查询行业研报。", {"code": _CODE}, ["code"]),
    _tool("query_market", "查询目标项目市场总览快照。", {}, []),
    _tool("query_news_radar", "查询新闻雷达。", {}, []),
    _tool("query_global_stock", "查询美股或其他全球市场行情。", {"code": _CODE}, ["code"]),
    _tool("query_hk_cashflow", "查询港股资金流向。", {"code": _CODE}, ["code"]),
]


def _json_result(value: Any) -> Any:
    """Round-trip through JSON so dates, Polars scalars and NaN never leak."""
    try:
        return json.loads(json.dumps(_json_safe(value), ensure_ascii=False, default=str))
    except Exception:
        return {"error": "结果无法序列化"}


def _error(message: str, **extra: Any) -> dict[str, Any]:
    return {"error": message, **extra}


def _query_quote(repo, quote_service, code: str) -> dict[str, Any]:
    symbol = normalize_symbol(repo, code)
    row = _quote(repo, quote_service, symbol)
    return {"symbol": symbol, "quote": row} if row is not None else _error("暂无行情记录", symbol=symbol)


def _query_kline(repo, code: str, days: int = 60) -> dict[str, Any]:
    symbol = normalize_symbol(repo, code)
    days = max(1, min(int(days or 60), 250))
    end = date.today()
    frame = repo.get_daily_asset(repo.resolve_asset_type(symbol), symbol, end - timedelta(days=days * 3), end)
    if frame.is_empty():
        return _error("暂无日线记录", symbol=symbol)
    keep = [
        "date", "open", "high", "low", "close", "volume", "change_pct", "ma5", "ma10", "ma20", "ma60",
        "macd_dif", "macd_dea", "macd_hist", "kdj_k", "kdj_d", "kdj_j", "rsi_6", "rsi_14", "rsi_24",
        "boll_upper", "boll_mid", "boll_lower", "atr_14", "vol_ratio_5d", "turnover_rate",
    ]
    rows = frame.tail(days).select([column for column in keep if column in frame.columns]).to_dicts()
    return {"symbol": symbol, "rows": _json_result(rows), "count": len(rows)}


def _query_financials(repo, data_dir, code: str, table: str | None = None) -> dict[str, Any]:
    symbol = normalize_symbol(repo, code)
    tables = [table] if table in {"metrics", "income", "cash_flow", "balance", "shares"} else ["metrics", "income"]
    out: dict[str, Any] = {"symbol": symbol}
    for name in tables:
        try:
            frame = get_financial_df(data_dir, name)
            if frame.is_empty() or "symbol" not in frame.columns:
                out[name] = []
                continue
            frame = frame.filter(pl.col("symbol") == symbol)
            if "period_end" in frame.columns:
                frame = frame.sort("period_end", descending=True).head(4)
            out[name] = _json_result(frame.to_dicts())
        except Exception as exc:  # noqa: BLE001
            logger.debug("financial tool failed: %s", name, exc_info=True)
            out[name] = []
    if not any(out.get(name) for name in tables):
        out["error"] = "暂无已同步财务记录"
    return out


def _query_valuation(repo, data_dir, quote_service, code: str) -> dict[str, Any]:
    symbol = normalize_symbol(repo, code)
    quote = _quote(repo, quote_service, symbol) or {}
    values = {key: quote.get(key) for key in ("pe", "pe_ttm", "pb", "ps", "market_cap", "float_market_cap") if quote.get(key) is not None}
    if not values:
        metrics = _query_financials(repo, data_dir, symbol, "metrics")
        rows = metrics.get("metrics") or []
        if rows:
            latest = rows[0]
            values = {key: latest.get(key) for key in ("pe", "pe_ttm", "pb", "ps", "market_cap", "float_market_cap") if latest.get(key) is not None}
    return {"symbol": symbol, "valuation": values, "note": "前向 PE、历史估值分位和一致预期未接入"} if values else _error("估值字段未接入", symbol=symbol)


def _query_lockup(repo, data_dir, code: str) -> dict[str, Any]:
    symbol = normalize_symbol(repo, code)
    result = _query_financials(repo, data_dir, symbol, "shares")
    result["note"] = "当前仅返回已同步股本字段，不是限售解禁日历"
    return result


def _query_company_info(repo, code: str) -> dict[str, Any]:
    symbol = normalize_symbol(repo, code)
    name_map = repo.get_name_map([symbol]) if hasattr(repo, "get_name_map") else {}
    result: dict[str, Any] = {"symbol": symbol, "name": name_map.get(symbol)}
    try:
        instruments = repo.get_instruments()
        if not instruments.is_empty() and "symbol" in instruments.columns:
            row = instruments.filter(pl.col("symbol") == symbol)
            if not row.is_empty():
                result.update(_json_result(row.to_dicts()[0]))
    except Exception:  # noqa: BLE001
        logger.debug("company info unavailable for %s", symbol, exc_info=True)
    return result


def _query_industry_comparison(repo, code: str) -> dict[str, Any]:
    symbol = normalize_symbol(repo, code)
    try:
        from app.services.sector_monitor import SectorMonitorService
        service = SectorMonitorService(repo)
        targets = service.list_targets()
        return {"symbol": symbol, "available_targets": _json_result(targets)}
    except Exception as exc:  # noqa: BLE001
        return _error(f"行业板块目录不可用: {type(exc).__name__}", symbol=symbol)


def _query_market(repo, quote_service, depth_service) -> dict[str, Any]:
    try:
        from app.services.market_overview_builder import build_market_overview
        overview = build_market_overview(repo, quote_service, depth_service, date.today())
        return _json_result(overview)
    except Exception as exc:  # noqa: BLE001
        logger.debug("market tool failed", exc_info=True)
        return _error(f"市场总览暂不可用: {type(exc).__name__}")


def exec_tool(
    name: str,
    args: dict[str, Any] | None,
    *,
    repo,
    data_dir,
    quote_service=None,
    depth_service=None,
) -> dict[str, Any]:
    """Execute a named tool and always return a JSON-serializable dict."""
    args = args if isinstance(args, dict) else {}
    try:
        if name == "query_quote":
            return _query_quote(repo, quote_service, str(args.get("code") or ""))
        if name == "query_kline":
            return _query_kline(repo, str(args.get("code") or ""), int(args.get("days") or 60))
        if name == "query_valuation":
            return _query_valuation(repo, data_dir, quote_service, str(args.get("code") or ""))
        if name == "query_financials":
            return _query_financials(repo, data_dir, str(args.get("code") or ""), args.get("table"))
        if name == "query_company_info":
            return _query_company_info(repo, str(args.get("code") or ""))
        if name == "query_lockup":
            return _query_lockup(repo, data_dir, str(args.get("code") or ""))
        if name == "query_concepts":
            symbol = normalize_symbol(repo, str(args.get("code") or ""))
            return {"symbol": symbol, **_json_result(_concept_rows(data_dir, symbol))}
        if name == "query_market":
            return _query_market(repo, quote_service, depth_service)
        if name == "query_industry_comparison":
            return _query_industry_comparison(repo, str(args.get("code") or ""))
        if name not in _TOOLS_WITH_DATA:
            return _error("数据未接入", tool=name)
        return _error("工具参数不完整")
    except Exception as exc:  # noqa: BLE001
        logger.warning("AI tool %s failed: %s", name, exc)
        return _error("工具执行失败", tool=name, detail=type(exc).__name__)


TOOL_NAMES = {item["function"]["name"] for item in TOOLS}
