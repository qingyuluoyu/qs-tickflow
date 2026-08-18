"""新浪快照行情: 收盘后补齐当日日K分区的兜底数据源。

背景: tickflow 免费档与 TeaJoin 的日K均为 T+1 发布(当日收盘数据次日才可见),
导致盘后管道跑完看板/日K仍停留在前一交易日。新浪 hq.sinajs.cn 快照在收盘后
即为定版数据, 用它把当日分区补齐; 次日管道 batch 同步会用权威数据覆写该分区
(append_daily 为 merge-upsert), 不会留下重复或脏数据。
"""

from __future__ import annotations

import logging
import random
import time

import httpx
import polars as pl

logger = logging.getLogger(__name__)

_SINA_URL = "https://hq.sinajs.cn/list={symbols}"
_HEADERS = {"Referer": "https://finance.sina.com.cn"}
_BATCH = 80
_BATCH_SLEEP = 0.15

_SUFFIX_PREFIX = {"SH": "sh", "SZ": "sz", "BJ": "bj"}


def _get(url: str, timeout: float = 10.0) -> str:
    """直连优先, 失败降级系统代理, 整体重试 3 轮。

    本机对国内财经站的连接两类瞬断都有: 直连被 RST、系统代理 CONNECT 被掐,
    且都是间歇性的, 因此每轮双通道各试一次。
    """
    last_exc: Exception | None = None
    for attempt in range(3):
        if attempt:
            time.sleep(0.6 * attempt + random.uniform(0, 0.3))
        for trust in (False, True):
            try:
                resp = httpx.get(url, headers=_HEADERS, timeout=timeout, trust_env=trust)
                resp.raise_for_status()
                resp.encoding = "gbk"
                return resp.text
            except Exception as e:  # noqa: BLE001
                last_exc = e
    raise last_exc if last_exc else RuntimeError(f"新浪快照请求失败: {url[:80]}")


def _sina_code(symbol: str) -> str | None:
    code, _, suffix = symbol.partition(".")
    prefix = _SUFFIX_PREFIX.get((suffix or "").upper())
    return f"{prefix}{code}" if prefix and code else None


def _parse_line(line: str, *, is_index: bool) -> dict | None:
    """解析单行 hq_str 快照。

    股票/指数字段布局一致: 名称,开,昨收,最新,高,低,买,卖,成交量,成交额,...,日期,时间
    成交量单位: 股票为股(需 /100 转为 canonical 的手), 指数与本地存储同刻度(不除)。
    """
    if "=" not in line or '"' not in line:
        return None
    key = line.split("=", 1)[0].strip().removeprefix("var hq_str_")
    payload = line.split('"', 2)[1] if line.count('"') >= 2 else ""
    if not payload:
        return None  # 长期停牌/无效代码返回空串
    f = payload.split(",")
    if len(f) < 31:
        return None
    try:
        volume = float(f[8])
        row = {
            "sina_code": key,
            "name": f[0],
            "open": float(f[1]),
            "prev_close": float(f[2]),
            "high": float(f[4]),
            "low": float(f[5]),
            "close": float(f[3]),
            "volume": volume if is_index else volume / 100.0,
            "amount": float(f[9]),
            "date": f[30],
        }
    except (ValueError, IndexError):
        return None
    return row


def _fetch_spot(
    symbols: list[str],
    *,
    asset_type: str = "stock",
    batch_sleep: float = _BATCH_SLEEP,
) -> pl.DataFrame:
    """按标的列表拉取新浪快照原始行 (含 name/prev_close), 列裁剪由调用方决定。"""
    is_index = asset_type == "index"
    code_map: dict[str, str] = {}
    for sym in symbols:
        sc = _sina_code(sym)
        if sc:
            code_map[sc] = sym
    if not code_map:
        return pl.DataFrame()

    rows: list[dict] = []
    codes = sorted(code_map)
    failed_batches = 0
    for i in range(0, len(codes), _BATCH):
        if i:
            time.sleep(batch_sleep + random.uniform(0, 0.1))
        chunk = codes[i : i + _BATCH]
        url = _SINA_URL.format(symbols=",".join(chunk))
        try:
            text = _get(url)
        except Exception as e:  # noqa: BLE001
            failed_batches += 1
            logger.warning("sina snapshot batch %d failed (%d codes): %s",
                           i // _BATCH + 1, len(chunk), e)
            continue
        for line in text.strip().splitlines():
            row = _parse_line(line, is_index=is_index)
            if row and row["sina_code"] in code_map:
                row["symbol"] = code_map.pop(row["sina_code"])
                rows.append(row)

    if failed_batches:
        logger.warning("sina snapshot: %d/%d batches failed",
                       failed_batches, (len(codes) + _BATCH - 1) // _BATCH)
    if not rows:
        return pl.DataFrame()
    return pl.DataFrame(rows)


def fetch_spot_daily(symbols: list[str], *, asset_type: str = "stock") -> pl.DataFrame:
    """按标的列表拉取新浪快照, 返回 canonical 日K列 (+date 为字符串, 调用方再 cast/过滤)。

    仅返回当日有成交的标的; 停牌(全 0)由调用方的 filter_halt_days 过滤,
    无数据(空串)在此直接丢弃。返回空 df 表示源不可用或全部无数据。
    """
    df = _fetch_spot(symbols, asset_type=asset_type)
    if df.is_empty():
        return df
    return df.select(["symbol", "date", "open", "high", "low", "close", "volume", "amount"])


def fetch_market_spot(symbols: list[str], *, asset_type: str = "stock") -> pl.DataFrame:
    """看板盘中快照入口: 在 canonical 列之外保留 prev_close/name, 不写入任何分区。

    ``prev_close`` 取新浪快照的昨收字段——除权除息日它是交易所调整后的
    基准价, 用它算盘中涨跌幅才不会把除权缺口误报成跌停。全市场一轮约
    5400 只/80 每批, 批次间隔压到 ~0.05s, 一轮控制在 20-30s。
    """
    df = _fetch_spot(symbols, asset_type=asset_type, batch_sleep=0.05)
    if df.is_empty():
        return df
    return df.select([
        "symbol", "date", "open", "high", "low", "close",
        "prev_close", "volume", "amount", "name",
    ])
