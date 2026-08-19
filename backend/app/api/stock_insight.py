"""个股洞察数据 API —— 估值分位 / 财务指标 / 研报 / 公告 / 新闻 / 资金流 / 龙虎榜。

路由前缀: /api/stock-insight
数据层: app.services.stock_insight（公开 HTTP 直爬，移植自 Vibe-Research astock.py）
"""
from __future__ import annotations

import logging
import re
import threading
import time

from fastapi import APIRouter, HTTPException, Query

from app.services import stock_insight as svc

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/stock-insight", tags=["stock-insight"])

_SYMBOL_RE = re.compile(r"^\d{6}\.(SH|SZ|BJ)$")


def _validate(symbol: str) -> str:
    """000001.SZ → 6 位 code；非法格式 400。"""
    if not _SYMBOL_RE.match(symbol):
        raise HTTPException(400, f"symbol 格式应为 000001.SZ / 600000.SH / 8xxxxx.BJ,收到: {symbol}")
    return svc.symbol_to_code(symbol)


# ---------------------------------------------------------------------------
# 简单内存 TTL 缓存（参考 Vibe app.py 的 _cached）
# ---------------------------------------------------------------------------

_cache: dict[str, tuple[float, object]] = {}
_cache_lock = threading.Lock()

_TTL_SLOW = 1800   # 估值 / 财务 / 龙虎榜: 30 分钟
_TTL_FAST = 900    # 公告 / 资金流: 15 分钟


def _cached(key: str, ttl: int, fn):
    """TTL 缓存 + 陈旧兜底：抓取失败时若有过期的旧数据，先返回旧数据（外部源偶发断连）。

    旧值保留在缓存里不删除，仅在成功时刷新时间戳；前端无从感知数据年龄，
    但「显示 30 分钟前的资金流」远好于「整板块空白」。
    """
    now = time.time()
    with _cache_lock:
        hit = _cache.get(key)
        if hit and now - hit[0] < ttl:
            return hit[1]
    try:
        value = fn()
    except Exception:
        with _cache_lock:
            hit = _cache.get(key)
            if hit is not None:
                logger.info("stock-insight 抓取失败,返回陈旧缓存: %s", key)
                return hit[1]
        raise
    with _cache_lock:
        _cache[key] = (now, value)
    return value


def _clear_cache() -> None:
    """测试用：清空全部缓存。"""
    with _cache_lock:
        _cache.clear()


def _fetch(fn, source: str):
    """外部抓取统一兜底：失败 502 + 简洁 detail。"""
    try:
        return fn()
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        logger.warning("stock-insight %s failed: %s", source, e)
        raise HTTPException(502, f"{source}数据源异常：{e}") from e


@router.get("/valuation")
def valuation(symbol: str = Query(...)):
    """估值历史分位（百度股市通）：PE-TTM / PB 当前值 + 历史分位带。"""
    code = _validate(symbol)
    return _cached(f"valuation:{code}", _TTL_SLOW, lambda: _fetch(lambda: svc.valuation_percentile(code), "估值"))


@router.get("/financials")
def financials(symbol: str = Query(...)):
    """财务关键指标（同花顺财务摘要，最新报告期）。"""
    code = _validate(symbol)
    return _cached(f"financials:{code}", _TTL_SLOW, lambda: _fetch(lambda: svc.financials(code), "财务"))


@router.get("/reports")
def reports(symbol: str = Query(...), pages: int = Query(2, ge=1, le=5)):
    """个股研报列表（东财，含 PDF 链接）。"""
    code = _validate(symbol)

    def run():
        rows = _fetch(lambda: svc.eastmoney_reports(code, max_pages=pages), "研报")
        for r in rows:
            r["pdfUrl"] = svc.pdf_url(r.get("infoCode", "")) if r.get("infoCode") else None
        return {"reports": rows}

    return _cached(f"reports:{code}:{pages}", _TTL_FAST, run)


@router.get("/announcements")
def announcements(symbol: str = Query(...)):
    """个股近期公告（东财）。"""
    code = _validate(symbol)
    data = _cached(f"ann:{code}", _TTL_FAST, lambda: _fetch(lambda: svc.announcements(code), "公告"))
    return {"announcements": data}


@router.get("/news")
def news(symbol: str = Query(...), limit: int = Query(20, ge=1, le=50)):
    """个股新闻（东财搜索）。"""
    code = _validate(symbol)
    data = _cached(f"news:{code}:{limit}", _TTL_FAST, lambda: _fetch(lambda: svc.stock_news(code, limit=limit), "新闻"))
    return {"news": data}


@router.get("/fund-flow")
def fund_flow(symbol: str = Query(...)):
    """个股资金流（日级，最近 120 交易日）。"""
    code = _validate(symbol)
    data = _cached(f"fundflow:{code}", _TTL_FAST, lambda: _fetch(lambda: svc.stock_fund_flow_120d(code), "资金流"))
    return {"rows": data}


@router.get("/dragon-tiger")
def dragon_tiger(symbol: str = Query(...)):
    """龙虎榜：近期上榜记录 + 最近一次买卖席位 TOP5 + 机构专用席位净买。"""
    code = _validate(symbol)
    return _cached(f"dt:{code}", _TTL_SLOW, lambda: _fetch(lambda: svc.dragon_tiger_board(code), "龙虎榜"))
