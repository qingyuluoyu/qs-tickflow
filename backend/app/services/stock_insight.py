"""个股洞察数据层 —— 移植自 Vibe-Research backend/astock.py（公开 HTTP 直爬，无数据库）。

数据源:
  - 估值历史分位  : 百度股市通 opendata（替代 akshare.stock_zh_valuation_baidu）
  - 财务指标      : 同花顺 basic.10jqka.com.cn 页面内嵌 JSON（替代 akshare.stock_financial_abstract_ths）
  - 个股新闻      : 东财 search-api-web（替代 akshare.stock_news_em，curl_cffi → requests）
  - 研报/公告/资金流/龙虎榜 : 东财 reportapi / np-anotice / push2his / datacenter（纯 requests 直接移植）

约定:
  - 全部同步函数，入参为 6 位 code；symbol(000001.SZ) → code 的转换在 API 层完成。
  - 网络/解析失败直接抛异常，由 API 层统一兜底成 502。
"""
from __future__ import annotations

import json
import os
import random
import re
import time
from datetime import datetime, timedelta

import requests

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"


# ---------------------------------------------------------------------------
# 代码转换
# ---------------------------------------------------------------------------

def symbol_to_code(symbol: str) -> str:
    """000001.SZ / 600000.SH / 8xxxxx.BJ → 6 位 code。"""
    return symbol.split(".")[0]


def code_to_secid(code: str) -> str:
    """6 位 code → 东财 secid。SH=1，SZ/BJ=0。"""
    market = 1 if code.startswith("6") else 0
    return f"{market}.{code}"


# ---------------------------------------------------------------------------
# 东财统一请求入口（移植 em_get：1s 限流 + 直连优先/代理降级）
# ---------------------------------------------------------------------------

_EM_MIN_INTERVAL = 1.0          # 两次东财请求最小间隔（秒），内置防封节流
_em_last_call = [0.0]
_EM_SESSIONS: dict = {}         # {direct(bool): requests.Session}

# 数据层连接模式：国内财经站本应直连——系统代理（Clash/V2Ray）常把国内站路由挂掉。
# 默认 auto：先试直连、失败降级系统代理，探测一次后固定。VR_DATA_PROXY=1 强制走代理。
_em_mode = ["proxy" if os.environ.get("VR_DATA_PROXY", "").strip().lower() in ("1", "true", "yes") else "auto"]


def _em_session(direct: bool) -> requests.Session:
    """direct=True → trust_env=False 忽略代理环境变量、直连（不重试，探测要快）。"""
    if direct in _EM_SESSIONS:
        return _EM_SESSIONS[direct]
    s = requests.Session()
    s.headers.update({"User-Agent": UA})
    s.trust_env = not direct
    try:
        from requests.adapters import HTTPAdapter
        from urllib3.util.retry import Retry

        retry = Retry(total=0) if direct else Retry(
            total=3, connect=3, backoff_factor=0.6,
            status_forcelist=[429, 500, 502, 503, 504], allowed_methods=["GET"])
        adapter = HTTPAdapter(max_retries=retry)
        s.mount("https://", adapter)
        s.mount("http://", adapter)
    except Exception:
        pass  # 老版本 urllib3 缺参数时降级为无重试
    _EM_SESSIONS[direct] = s
    return s


def em_get(url: str, params: dict | None = None, headers: dict | None = None, timeout: int = 15):
    """东财统一请求入口：串行限流 + 直连优先、失败降级系统代理 + 多轮重试。

    国内财经站在本机常见两类瞬断：直连被 RST、系统代理对国内域名 CONNECT 被掐，
    两者都是间歇性的，所以最后一轮整体重试 2 次（带退避抖动）。
    """
    wait = _EM_MIN_INTERVAL - (time.time() - _em_last_call[0])
    if wait > 0:
        time.sleep(wait + random.uniform(0.1, 0.5))
    last_exc: Exception | None = None
    try:
        for attempt in range(3):
            if attempt > 0:
                time.sleep(0.8 * attempt + random.uniform(0, 0.4))
            # 每轮都双路尝试：优先上次成功的通道，失败立即换另一条。
            # 直连 RST 与代理断连都是间歇性的，锁定单通道重试没有意义。
            mode = _em_mode[0]
            order = ("direct", "proxy") if mode != "proxy" else ("proxy", "direct")
            for m in order:
                try:
                    r = _em_session(m == "direct").get(
                        url, params=params, headers=headers,
                        timeout=min(timeout, 8) if m == "direct" else timeout)
                    _em_mode[0] = m
                    return r
                except Exception as e:
                    last_exc = e
        raise last_exc if last_exc else RuntimeError(f"请求失败: {url}")
    finally:
        _em_last_call[0] = time.time()


_DATACENTER_URL = "https://datacenter-web.eastmoney.com/api/data/v1/get"


def eastmoney_datacenter(report_name: str, columns: str = "ALL", filter_str: str = "",
                         page_size: int = 50, sort_columns: str = "", sort_types: str = "-1") -> list[dict]:
    """东财数据中心统一查询 —— 龙虎榜等 reportName+filter 模式报表共用（已内置限流）。"""
    params = {
        "reportName": report_name, "columns": columns, "filter": filter_str,
        "pageNumber": "1", "pageSize": str(page_size),
        "sortColumns": sort_columns, "sortTypes": sort_types, "source": "WEB", "client": "WEB",
    }
    d = em_get(_DATACENTER_URL, params=params, timeout=15).json()
    if d.get("result") and d["result"].get("data"):
        return d["result"]["data"]
    return []


# ---------------------------------------------------------------------------
# 1. 估值历史分位（百度股市通 opendata，替代 akshare.stock_zh_valuation_baidu）
# ---------------------------------------------------------------------------

_BAIDU_VALUATION_URL = "https://gushitong.baidu.com/opendata"


def _baidu_valuation_series(code: str, indicator: str, period: str) -> list[float]:
    """百度股市通估值序列（如 市盈率(TTM)/市净率），返回按时间升序的数值列表。"""
    params = {
        "openapi": "1", "dspName": "iphone", "tn": "tangram", "client": "app",
        "query": indicator, "code": code, "word": "", "resource_id": "51171",
        "market": "ab", "tag": indicator, "chart_select": period,
        "industry_select": "", "skip_industry": "1", "finClientType": "pc",
    }
    r = em_get(_BAIDU_VALUATION_URL, params=params, headers={"User-Agent": UA}, timeout=15)
    body = r.json()["Result"][0]["DisplayData"]["resultData"]["tplData"]["result"]["chartInfo"][0]["body"]
    vals = []
    for _date, value in body:
        try:
            vals.append(float(value))
        except (TypeError, ValueError):
            continue
    return vals


def valuation_percentile(code: str, period: str = "近五年") -> dict:
    """历史估值分位：PE-TTM / PB 的当前值 + 历史 20/50/80 分位带 + 所处分位。"""

    def _q(vals: list, p: float) -> float:
        if not vals:
            return 0.0
        idx = p * (len(vals) - 1)
        lo = int(idx)
        if lo + 1 >= len(vals):
            return vals[-1]
        frac = idx - lo
        return vals[lo] * (1 - frac) + vals[lo + 1] * frac

    metrics = {}
    for key, ind in (("pe_ttm", "市盈率(TTM)"), ("pb", "市净率")):
        try:
            raw = _baidu_valuation_series(code, ind, period)
            if not raw:
                continue
            cur = float(raw[-1])
            s = sorted(raw)
            below = sum(1 for x in s if x < cur)
            metrics[key] = {
                "current": round(cur, 2),
                "percentile": round(below / max(len(s) - 1, 1) * 100, 1),
                "min": round(s[0], 2), "max": round(s[-1], 2),
                "p20": round(_q(s, 0.2), 2), "p50": round(_q(s, 0.5), 2), "p80": round(_q(s, 0.8), 2),
                "n": len(s),
            }
        except Exception:
            continue
    return {"period": "近5年", "metrics": metrics}


# ---------------------------------------------------------------------------
# 2. 财务指标（同花顺财务摘要页面内嵌 JSON，替代 akshare.stock_financial_abstract_ths）
# ---------------------------------------------------------------------------

_THS_FINANCE_TPL = "https://basic.10jqka.com.cn/new/{code}/finance.html"
_THS_HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                              "(KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36"}


def financials(code: str) -> dict:
    """财务关键指标（同花顺财务摘要，最新报告期）：营收/净利/ROE/毛利率等。

    页面把财务 JSON 藏在 <p id="main" style="display:none"> 里，无需 bs4，正则取出即可。
    """
    r = em_get(_THS_FINANCE_TPL.format(code=code), headers=_THS_HEADERS, timeout=15)
    m = re.search(r'<p id="main"[^>]*>(.*?)</p>', r.text, re.S)
    if not m:
        raise RuntimeError(f"同花顺财务页未取到内嵌数据: {code}")
    data_json = json.loads(m.group(1))
    # 结构（同 akshare）：report[0] 是报告期日期行（降序），report[1:] 是指标数据行，
    # 与 title[1:] 的指标名一一对应；转置后每行 = 一个报告期。
    periods = data_json["report"][0]
    metric_names = [item[0] if isinstance(item, list) else item for item in data_json["title"][1:]]
    rows = []
    for j, period in enumerate(periods):
        row = {"报告期": period}
        for i, name in enumerate(metric_names):
            row[name] = data_json["report"][i + 1][j]
        rows.append(row)
    if not rows:
        return {}
    rows.sort(key=lambda r: str(r.get("报告期", "")))
    row = rows[-1]  # 最新报告期

    def g(k):
        v = row.get(k)
        return None if v in (False, "false", "", None) else v

    def to_amount(v):
        """'922.78亿' / '1234.5万' / 裸数字 → 元(float);无法解析 → None。"""
        if v is None:
            return None
        s = str(v).replace(",", "").strip()
        m2 = re.match(r"^(-?[\d.]+)(亿|万)?$", s)
        if not m2:
            return None
        mult = {"亿": 1e8, "万": 1e4, None: 1.0}[m2.group(2)]
        return float(m2.group(1)) * mult

    def to_pct(v):
        """'1.30%' → 1.30;无法解析 → None。"""
        if v is None:
            return None
        s = str(v).strip().rstrip("%")
        try:
            return float(s)
        except ValueError:
            return None

    def to_num(v):
        """'35.5700' → 35.57;无法解析 → None。"""
        if v is None:
            return None
        try:
            return float(str(v).strip())
        except ValueError:
            return None

    return {
        "period": g("报告期"),
        "revenue": to_amount(g("营业总收入")), "revenue_yoy": to_pct(g("营业总收入同比增长率")),
        "net_profit": to_amount(g("净利润")), "net_profit_yoy": to_pct(g("净利润同比增长率")),
        "eps": to_num(g("基本每股收益")), "bvps": to_num(g("每股净资产")),
        "roe": to_pct(g("净资产收益率")), "gross_margin": to_pct(g("销售毛利率")), "net_margin": to_pct(g("销售净利率")),
        "op_cf_ps": to_num(g("每股经营现金流")),
    }


# ---------------------------------------------------------------------------
# 3. 近期研报（东财 reportapi，纯 requests 直接移植）
# ---------------------------------------------------------------------------

_REPORT_API = "https://reportapi.eastmoney.com/report/list"
_PDF_TPL = "https://pdf.dfcfw.com/pdf/H3_{info_code}_1.pdf"


def pdf_url(info_code: str) -> str:
    return _PDF_TPL.format(info_code=info_code)


def eastmoney_reports(code: str, max_pages: int = 3) -> list[dict]:
    """按个股代码拉研报列表（qType=0）。PDF 链接由调用方用 pdf_url(infoCode) 拼装。"""
    headers = {"User-Agent": UA, "Referer": "https://data.eastmoney.com/"}
    out: list[dict] = []
    for page in range(1, max_pages + 1):
        params = {
            "industryCode": "*", "pageSize": "100", "industry": "*",
            "rating": "*", "ratingChange": "*",
            "beginTime": "2000-01-01", "endTime": "2030-01-01",
            "pageNo": str(page), "fields": "", "qType": "0",
            "orgCode": "", "code": code, "rcode": "",
            "p": str(page), "pageNum": str(page), "pageNumber": str(page),
        }
        r = em_get(_REPORT_API, params=params, headers=headers, timeout=30)
        d = r.json()
        rows = d.get("data") or []
        if not rows:
            break
        out.extend(rows)
        if page >= (d.get("TotalPage", 1) or 1):
            break
        time.sleep(0.3)
    return out


# ---------------------------------------------------------------------------
# 4. 近期公告（东财 np-anotice，纯 requests 直接移植）
# ---------------------------------------------------------------------------

def announcements(code: str, limit: int = 15) -> list[dict]:
    """个股近期公告（东财公开接口）。返回 日期/标题/类型/详情链接。"""
    r = em_get(
        "https://np-anotice-stock.eastmoney.com/api/security/ann",
        params={"sr": -1, "page_size": limit, "page_index": 1, "ann_type": "A",
                "client_source": "web", "stock_list": code, "f_node": 0, "s_node": 0},
        headers={"User-Agent": UA}, timeout=20,
    )
    lst = (r.json().get("data") or {}).get("list") or []
    out = []
    for a in lst:
        cols = [c.get("column_name") for c in (a.get("columns") or []) if c.get("column_name")]
        art = a.get("art_code", "")
        out.append({
            "date": (a.get("notice_date", "") or "")[:10],
            "title": a.get("title", ""),
            "type": cols[0] if cols else "",
            "url": f"https://data.eastmoney.com/notices/detail/{code}/{art}.html" if art else "",
        })
    return out


# ---------------------------------------------------------------------------
# 5. 个股新闻（东财 search-api-web JSONP，替代 akshare.stock_news_em）
# ---------------------------------------------------------------------------

_NEWS_API = "https://search-api-web.eastmoney.com/search/jsonp"
_EM_TAG_RE = re.compile(r"</?em>")


def stock_news(code: str, limit: int = 20) -> list[dict]:
    """个股新闻（东财搜索）。返回 [{新闻标题, 发布时间, 文章来源, 新闻链接}]。"""
    inner_param = {
        "uid": "", "keyword": code, "type": ["cmsArticleWebOld"],
        "client": "web", "clientType": "web", "clientVersion": "curr",
        "param": {"cmsArticleWebOld": {
            "searchScope": "default", "sort": "default",
            "pageIndex": 1, "pageSize": min(max(limit, 1), 100),
            "preTag": "<em>", "postTag": "</em>",
        }},
    }
    cb = f"jQuery{random.randint(10**20, 10**21 - 1)}_{int(time.time() * 1000)}"
    params = {"cb": cb, "param": json.dumps(inner_param, ensure_ascii=False),
              "_": str(int(time.time() * 1000))}
    headers = {"User-Agent": UA, "Referer": f"https://so.eastmoney.com/news/s?keyword={code}"}
    r = em_get(_NEWS_API, params=params, headers=headers, timeout=15)
    text = r.text
    payload = text[text.index("(") + 1:text.rindex(")")]
    items = (json.loads(payload).get("result") or {}).get("cmsArticleWebOld") or []
    out = []
    for it in items[:limit]:
        out.append({
            "新闻标题": _EM_TAG_RE.sub("", it.get("title", "") or ""),
            "发布时间": it.get("date", ""),
            "文章来源": it.get("mediaName", ""),
            "新闻链接": f"http://finance.eastmoney.com/a/{it.get('code', '')}.html",
        })
    return out


# ---------------------------------------------------------------------------
# 6. 资金面（东财 push2his fflow/daykline，直接移植）
# ---------------------------------------------------------------------------

# push2his 是本机唯一有完整 120 日历史的 fflow 域名;push2/push2delay 只回当日 1 行,
# emhsmarketwg 无此接口——无可用镜像,只能靠 em_get 重试 + API 层陈旧缓存兜底
_FFLOW_HOSTS = ("push2his.eastmoney.com",)


def stock_fund_flow_120d(code: str) -> list[dict]:
    """个股资金流（日级，最近 120 交易日）：主力 / 小单 / 中单 / 大单 / 超大单净流入（元）。"""
    params = {
        "secid": code_to_secid(code),
        "fields1": "f1,f2,f3,f7",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f62,f63,f64,f65",
        "lmt": "120",
    }
    headers = {"User-Agent": UA, "Referer": "https://quote.eastmoney.com/", "Origin": "https://quote.eastmoney.com"}
    d: dict = {}
    last_exc: Exception | None = None
    for host in _FFLOW_HOSTS:
        try:
            d = em_get(f"https://{host}/api/qt/stock/fflow/daykline/get",
                       params=params, headers=headers, timeout=15).json()
            break
        except Exception as e:  # noqa: BLE001
            last_exc = e
    else:
        raise last_exc if last_exc else RuntimeError("资金流接口不可用")
    rows = []
    for line in (d.get("data") or {}).get("klines", []):
        p = line.split(",")
        if len(p) >= 6:
            def _f(x):
                try:
                    return float(x) if x not in ("-", "") else 0.0
                except ValueError:
                    return 0.0
            rows.append({
                "date": p[0], "main_net": _f(p[1]), "small_net": _f(p[2]),
                "mid_net": _f(p[3]), "large_net": _f(p[4]), "super_net": _f(p[5]),
            })
    return rows


# ---------------------------------------------------------------------------
# 7. 龙虎榜（东财 datacenter 三报表，直接移植）
# ---------------------------------------------------------------------------

def dragon_tiger_board(code: str, trade_date: str | None = None, look_back: int = 30) -> dict:
    """龙虎榜：该股近期上榜记录 + 最近一次买卖席位 TOP5 + 机构专用席位净买。"""
    trade_date = trade_date or datetime.now().strftime("%Y-%m-%d")
    start = (datetime.strptime(trade_date, "%Y-%m-%d") - timedelta(days=look_back)).strftime("%Y-%m-%d")
    records = []
    data = eastmoney_datacenter(
        "RPT_DAILYBILLBOARD_DETAILSNEW",
        filter_str=f'(TRADE_DATE>=\'{start}\')(TRADE_DATE<=\'{trade_date}\')(SECURITY_CODE="{code}")',
        page_size=50, sort_columns="TRADE_DATE", sort_types="-1")
    for r in data:
        records.append({
            "date": str(r.get("TRADE_DATE", ""))[:10],
            "reason": r.get("EXPLANATION", ""),
            "net_buy": round((r.get("BILLBOARD_NET_AMT") or 0) / 10000, 1),  # 万元
            "turnover": round(float(r.get("TURNOVERRATE") or 0), 2),
        })

    seats = {"buy": [], "sell": []}
    institution = {"buy_amt": 0.0, "sell_amt": 0.0, "net_amt": 0.0}
    if records:
        latest = records[0]["date"]
        buy_data = eastmoney_datacenter(
            "RPT_BILLBOARD_DAILYDETAILSBUY",
            filter_str=f'(TRADE_DATE=\'{latest}\')(SECURITY_CODE="{code}")',
            page_size=10, sort_columns="BUY", sort_types="-1")
        sell_data = eastmoney_datacenter(
            "RPT_BILLBOARD_DAILYDETAILSSELL",
            filter_str=f'(TRADE_DATE=\'{latest}\')(SECURITY_CODE="{code}")',
            page_size=10, sort_columns="SELL", sort_types="-1")
        for r in buy_data[:5]:
            seats["buy"].append({"name": r.get("OPERATEDEPT_NAME", ""),
                                 "buy_amt": round((r.get("BUY") or 0) / 10000, 1),
                                 "sell_amt": round((r.get("SELL") or 0) / 10000, 1),
                                 "net": round((r.get("NET") or 0) / 10000, 1)})
        for r in sell_data[:5]:
            seats["sell"].append({"name": r.get("OPERATEDEPT_NAME", ""),
                                  "buy_amt": round((r.get("BUY") or 0) / 10000, 1),
                                  "sell_amt": round((r.get("SELL") or 0) / 10000, 1),
                                  "net": round((r.get("NET") or 0) / 10000, 1)})
        for detail, side in ((buy_data, "buy"), (sell_data, "sell")):
            for r in detail:
                if str(r.get("OPERATEDEPT_CODE", "")) == "0":  # 机构专用席位
                    amt = (r.get("BUY") or 0) if side == "buy" else (r.get("SELL") or 0)
                    institution[f"{side}_amt"] += amt
        institution["buy_amt"] = round(institution["buy_amt"] / 10000, 1)
        institution["sell_amt"] = round(institution["sell_amt"] / 10000, 1)
        institution["net_amt"] = round(institution["buy_amt"] - institution["sell_amt"], 1)
    return {"records": records, "seats": seats, "institution": institution}
