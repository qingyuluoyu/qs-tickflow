"""多空辩论服务。

阶段一只使用目标项目已有的数据层，固定事实底稿后再依次生成多方、空方、
反驳和中立主持内容。这个模块只负责编排，不引入新的数据源或买卖结论。
"""
from __future__ import annotations

import asyncio
import json
import logging
import math
import re
from datetime import date, timedelta
from pathlib import Path
from typing import Any, AsyncIterator

import polars as pl

from app.services.financial_sync import get_financial_df

logger = logging.getLogger(__name__)

NO_RECORD = "（当前未接入该数据项，不能据此推断。）"
_SECTION_CAP = 6000
_CODE_RE = re.compile(r"^\d{6}$")

# 阶段一只声明目标项目确实能提供的五项；其余缺口保留在 dossier 中。
_DOSSIER_TITLES = (
    ("quote", "实时行情"),
    ("valuation", "估值与一致预期（仅 PE/PB/市值）"),
    ("financials", "最新财报关键指标"),
    ("kline", "近 60 日价格走势"),
    ("concepts", "板块与概念归属"),
)
_UNAVAILABLE_TITLES = [
    "估值历史分位", "资金流向", "融资融券", "股东户数", "近期公告",
    "限售解禁", "近期研报", "近期新闻",
]

_ROLE_PROMPTS = {
    "bull": """你是一名多方研究员。基于同一份客观底稿，找出支持这家公司基本面或技术状态的证据，尽可能有力地立论。
输出格式：
1. **核心论点**（一句话）
2. **支撑证据**（3-5 条，每条写出依据的具体数据）
3. **这套逻辑成立的前提**
""",
    "bear": """你是一名空方研究员。基于同一份客观底稿，找出基本面、估值或技术状态中的风险与疑点，尽可能有力地质疑。
输出格式：
1. **核心质疑**（一句话）
2. **风险证据**（3-5 条，每条写出依据的具体数据）
3. **这套逻辑成立的前提**
""",
    "bull_rebut": """你是多方研究员。上面是空方的质疑，请逐条回应：哪些质疑你承认，哪些可由数据反驳，哪些属于双方都没有数据、只能存疑。不要重复第一轮论述。""",
    "bear_rebut": """你是空方研究员。上面是多方的论述，请逐条回应：哪些论点你承认，哪些可由数据反驳，哪些属于双方都没有数据、只能存疑。不要重复第一轮质疑。""",
    "referee": """你是中立主持人。不要裁决谁对谁错，只把讨论沉淀为：
1. **双方共识**（2-4 条）
2. **真正的分歧点**（3-5 条，写清双方观点及分歧根源）
3. **验证清单**（要观察什么数据、去哪里看、什么时候能看到）
4. **数据缺口**
绝对不要输出结论倾向、买卖建议、目标价、评级或更认同哪一方。""",
}

_COMMON_RULES = """
共同规则（必须遵守）：
- 只能使用底稿里的数据立论。底稿没有的数字一律不许编，需要但缺失的明确写“该数据缺失”。
- 每条论点标出所依据的具体数据；没有数据支撑的直觉判断标注“无数据支撑”。
- 不预测股价涨跌与具体价位，不给买卖时机、目标价、仓位或任何操作指令。
- 使用简洁中文、条目化输出。全文只做客观研究讨论，不构成投资建议。
"""

_STAGE_LABEL = {
    "bull": "多方研究员",
    "bear": "空方研究员",
    "bull_rebut": "多方反驳",
    "bear_rebut": "空方反驳",
    "referee": "中立主持 · 分歧与验证清单",
}


def _json_safe(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (date,)):
        return value.isoformat()
    if isinstance(value, float):
        return None if not math.isfinite(value) else round(value, 6)
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    return value


def normalize_symbol(repo, code: str) -> str:
    """接受 6 位代码或标准 symbol，统一成仓库使用的 symbol。"""
    value = str(code or "").strip().upper()
    if not _CODE_RE.fullmatch(value):
        return value
    try:
        instruments = repo.get_instruments()
        if not instruments.is_empty() and {"code", "symbol"}.issubset(instruments.columns):
            hit = instruments.filter(pl.col("code").cast(pl.Utf8) == value)
            if not hit.is_empty():
                return str(hit[0, "symbol"])
    except Exception:  # noqa: BLE001 - 兜底规则仍能支持常见 A 股代码
        logger.debug("instrument lookup failed for %s", value, exc_info=True)
    return f"{value}.SH" if value.startswith(("5", "6", "68", "9")) else f"{value}.SZ"


def _quote(repo, quote_service, symbol: str) -> dict[str, Any] | None:
    try:
        if quote_service is not None:
            df = quote_service.get_quotes_compat()
            if not df.is_empty() and "symbol" in df.columns:
                row = df.filter(pl.col("symbol") == symbol)
                if not row.is_empty():
                    return _json_safe(row.to_dicts()[0])
    except Exception:  # noqa: BLE001
        logger.debug("quote cache unavailable for %s", symbol, exc_info=True)
    try:
        end = date.today()
        df = repo.get_daily_asset(repo.resolve_asset_type(symbol), symbol, end - timedelta(days=10), end)
        if not df.is_empty():
            return _json_safe(df.tail(1).to_dicts()[0])
    except Exception:  # noqa: BLE001
        logger.debug("daily quote fallback unavailable for %s", symbol, exc_info=True)
    return None


def _financial_rows(data_dir: Path, symbol: str) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = {}
    for table in ("metrics", "income"):
        try:
            df = get_financial_df(data_dir, table)
            if df.is_empty() or "symbol" not in df.columns:
                result[table] = []
                continue
            df = df.filter(pl.col("symbol") == symbol)
            if "period_end" in df.columns:
                df = df.sort("period_end", descending=True).head(2)
            rows = []
            for row in df.to_dicts():
                row.pop("symbol", None)
                rows.append(_json_safe(row))
            result[table] = rows
        except Exception:  # noqa: BLE001
            logger.debug("financial table unavailable: %s", table, exc_info=True)
            result[table] = []
    return result


def _kline_rows(repo, symbol: str) -> list[dict[str, Any]]:
    end = date.today()
    df = repo.get_daily_asset(repo.resolve_asset_type(symbol), symbol, end - timedelta(days=180), end)
    if df.is_empty():
        return []
    keep = [
        "date", "open", "high", "low", "close", "volume", "change_pct",
        "ma5", "ma10", "ma20", "ma60", "macd_dif", "macd_dea", "macd_hist",
        "kdj_k", "kdj_d", "kdj_j", "rsi_6", "rsi_14", "rsi_24",
        "boll_upper", "boll_mid", "boll_lower", "atr_14", "vol_ratio_5d", "turnover_rate",
    ]
    rows = df.tail(60).select([c for c in keep if c in df.columns]).to_dicts()
    return [_json_safe(row) for row in rows]


def _concept_rows(data_dir: Path, symbol: str) -> dict[str, Any]:
    """从目标项目的 ext_data 快照读取概念/行业标签。"""
    out: dict[str, Any] = {"concepts": [], "industries": []}
    for config_id, key in (("ext_gn_ths", "concepts"), ("ext_hy_ths", "industries")):
        base = data_dir / "ext_data" / config_id
        files = sorted(base.glob("*.parquet"))
        if not files:
            continue
        try:
            df = pl.read_parquet(files[-1])
            symbol_col = next((c for c in ("symbol", "code", "股票代码", "代码") if c in df.columns), None)
            if symbol_col is None:
                continue
            hit = df.filter(pl.col(symbol_col).cast(pl.Utf8).str.to_uppercase() == symbol)
            if hit.is_empty() and symbol.endswith((".SH", ".SZ")):
                code = symbol.split(".", 1)[0]
                hit = df.filter(pl.col(symbol_col).cast(pl.Utf8) == code)
            if not hit.is_empty():
                row = hit.to_dicts()[0]
                value_col = next((c for c in ("所属概念", "所属同花顺行业", "concepts", "industries", "概念", "行业") if c in row), None)
                if value_col:
                    raw = row[value_col]
                    out[key] = raw if isinstance(raw, list) else [x.strip() for x in re.split(r"[;,，；|]+", str(raw)) if x.strip()]
        except Exception:  # noqa: BLE001
            logger.debug("concept snapshot unavailable: %s", config_id, exc_info=True)
    return out


def build_dossier(repo, data_dir: Path, code: str, quote_service=None) -> dict[str, Any]:
    symbol = normalize_symbol(repo, code)
    fins = _financial_rows(data_dir, symbol)
    quote = _quote(repo, quote_service, symbol)
    metrics = fins.get("metrics", [])
    valuation = {}
    if metrics:
        latest = metrics[0]
        for key in ("pe", "pe_ttm", "pb", "market_cap", "float_market_cap"):
            if key in latest and latest[key] is not None:
                valuation[key] = latest[key]
    kline = _kline_rows(repo, symbol)
    concepts = _concept_rows(data_dir, symbol)
    sections: list[dict[str, Any]] = [
        {"title": _DOSSIER_TITLES[0][1], "tool": "quote_service/repository", "data": quote or NO_RECORD, "ok": quote is not None},
        {"title": _DOSSIER_TITLES[1][1], "tool": "financial_sync.metrics", "data": valuation or NO_RECORD, "ok": bool(valuation)},
        {"title": _DOSSIER_TITLES[2][1], "tool": "financial_sync", "data": fins, "ok": any(fins.values())},
        {"title": _DOSSIER_TITLES[3][1], "tool": "KlineRepository", "data": kline or NO_RECORD, "ok": bool(kline)},
        {"title": _DOSSIER_TITLES[4][1], "tool": "ext_data/ext_presets", "data": concepts, "ok": bool(concepts.get("concepts") or concepts.get("industries"))},
    ]
    missing = [s["title"] for s in sections if not s["ok"]] + list(_UNAVAILABLE_TITLES)
    return {"code": code, "symbol": symbol, "sections": sections, "missing": missing}


def dossier_text(dossier: dict[str, Any]) -> str:
    parts = [
        f"【客观事实底稿 · {dossier['symbol']}】",
        "以下全部为目标项目现有数据层读取的客观数据，不含任何观点：",
        "",
    ]
    for section in dossier["sections"]:
        data = section["data"]
        body = data if isinstance(data, str) else json.dumps(data, ensure_ascii=False, default=str)[:_SECTION_CAP]
        parts.append(f"## {section['title']}（来源 {section['tool']}）\n{body}\n")
    if dossier["missing"]:
        parts.append("## 数据缺口\n以下数据项目前未接入或本次无记录，立论时不得臆测：" + "、".join(dict.fromkeys(dossier["missing"])))
    return "\n".join(parts)


def _stage_plan(rounds: int) -> list[str]:
    return ["bull", "bear", "bull_rebut", "bear_rebut", "referee"] if rounds >= 2 else ["bull", "bear", "referee"]


def _build_messages(stage: str, facts: str, transcript: list[dict[str, str]]) -> list[dict[str, str]]:
    system = _ROLE_PROMPTS[stage] + _COMMON_RULES + "\n\n" + facts
    context: list[str] = []
    for item in transcript:
        if stage == "bull" or (stage == "bear" and item["stage"] != "bull"):
            continue
        context.append(f"【{_STAGE_LABEL[item['stage']]}的发言】\n{item['content']}")
    prompt = "\n\n".join(context) + "\n\n请按你的角色要求输出。" if context else "请基于底稿开始你的陈述。"
    return [{"role": "system", "content": system}, {"role": "user", "content": prompt}]


async def run_debate_stream(repo, data_dir: Path, code: str, rounds: int = 1, quote_service=None) -> AsyncIterator[str]:
    from app.services.ai_provider import stream_ai_text

    def emit(payload: dict[str, Any]) -> str:
        return json.dumps(payload, ensure_ascii=False, default=str)

    yield emit({"type": "status", "message": "正在拉取客观事实底稿…"})
    try:
        symbol = normalize_symbol(repo, code)
        # 统一在工作线程执行 Polars/文件读取，避免阻塞 FastAPI 事件循环。
        dossier = await asyncio.to_thread(build_dossier, repo, data_dir, code, quote_service)
        total = len(dossier["sections"])
        for loaded, section in enumerate(dossier["sections"], start=1):
            yield emit({"type": "dossier_progress", "title": section["title"], "ok": section["ok"], "loaded": loaded, "total": total})
        if not any(section["ok"] for section in dossier["sections"]):
            yield emit({"type": "error", "message": f"标的 {symbol} 未能取到客观数据，无法开始辩论"})
            return
        yield emit({"type": "dossier", "sections": [{"title": s["title"], "tool": s["tool"]} for s in dossier["sections"]], "missing": dossier["missing"]})
        facts = dossier_text(dossier)
        transcript: list[dict[str, str]] = []
        for stage in _stage_plan(rounds):
            label = _STAGE_LABEL[stage]
            yield emit({"type": "stage", "stage": stage, "label": label})
            buf: list[str] = []
            try:
                async for chunk in stream_ai_text(_build_messages(stage, facts, transcript), temperature=0.5, max_tokens=4000, timeout=180.0):
                    if chunk:
                        buf.append(chunk)
                        yield emit({"type": "delta", "stage": stage, "text": chunk})
            except Exception as exc:  # noqa: BLE001
                logger.exception("debate stage failed: %s", stage)
                message = f"{label}生成失败：{exc}"
                yield emit({"type": "error", "stage": stage, "message": message})
                yield emit({"type": "stage_done", "stage": stage, "label": label, "content": f"（{message}）", "failed": True})
                continue
            content = "".join(buf).strip()
            transcript.append({"stage": stage, "content": content})
            yield emit({"type": "stage_done", "stage": stage, "label": label, "content": content})
        yield emit({"type": "done", "code": code, "symbol": symbol, "stages": transcript})
    except Exception as exc:  # noqa: BLE001
        logger.exception("debate failed for %s", code)
        yield emit({"type": "error", "message": f"多空辩论失败：{exc}"})
