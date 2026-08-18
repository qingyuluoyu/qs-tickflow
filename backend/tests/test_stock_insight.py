"""stock-insight API 测试：外部 HTTP 全部 monkeypatch 到 service 层，验证参数校验、响应包装、缓存。"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import stock_insight as api
from app.services import stock_insight as svc


@pytest.fixture()
def client():
    api._clear_cache()  # noqa: SLF001
    app = FastAPI()
    app.include_router(api.router)
    with TestClient(app) as c:
        yield c
    api._clear_cache()  # noqa: SLF001


# ---------------------------------------------------------------------------
# 参数校验
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("symbol", ["000001", "000001.sh", "00001.SZ", "600000.XS", "abcdef.SZ"])
def test_invalid_symbol_rejected(client, symbol):
    for path in ("/api/stock-insight/valuation", "/api/stock-insight/financials",
                 "/api/stock-insight/reports", "/api/stock-insight/announcements",
                 "/api/stock-insight/news", "/api/stock-insight/fund-flow",
                 "/api/stock-insight/dragon-tiger"):
        r = client.get(path, params={"symbol": symbol})
        assert r.status_code == 400, (path, symbol, r.text)


def test_reports_pages_out_of_range(client):
    assert client.get("/api/stock-insight/reports", params={"symbol": "000001.SZ", "pages": 0}).status_code == 422
    assert client.get("/api/stock-insight/reports", params={"symbol": "000001.SZ", "pages": 6}).status_code == 422


def test_news_limit_out_of_range(client):
    assert client.get("/api/stock-insight/news", params={"symbol": "000001.SZ", "limit": 0}).status_code == 422
    assert client.get("/api/stock-insight/news", params={"symbol": "000001.SZ", "limit": 51}).status_code == 422


# ---------------------------------------------------------------------------
# 响应包装形状
# ---------------------------------------------------------------------------

def test_valuation_shape(client, monkeypatch):
    payload = {"period": "近5年", "metrics": {"pe_ttm": {"current": 10.0, "percentile": 42.0,
               "min": 6.0, "max": 20.0, "p20": 8.0, "p50": 10.0, "p80": 15.0, "n": 1200}}}
    monkeypatch.setattr(svc, "valuation_percentile", lambda code: payload)
    r = client.get("/api/stock-insight/valuation", params={"symbol": "600000.SH"})
    assert r.status_code == 200
    assert r.json() == payload


def test_financials_shape(client, monkeypatch):
    payload = {"period": "2025-06-30", "revenue": "100亿", "revenue_yoy": "5.2%",
               "net_profit": "10亿", "net_profit_yoy": "3.1%", "eps": "1.2元",
               "bvps": "15元", "roe": "8.5%", "gross_margin": "40%", "net_margin": "10%",
               "op_cf_ps": "0.8元"}
    monkeypatch.setattr(svc, "financials", lambda code: payload)
    r = client.get("/api/stock-insight/financials", params={"symbol": "000001.SZ"})
    assert r.status_code == 200
    assert r.json() == payload


def test_reports_wraps_and_adds_pdf_url(client, monkeypatch):
    monkeypatch.setattr(svc, "eastmoney_reports",
                        lambda code, max_pages: [{"infoCode": "AP123", "title": "t"}, {"title": "no-code"}])
    r = client.get("/api/stock-insight/reports", params={"symbol": "600000.SH", "pages": 2})
    assert r.status_code == 200
    rows = r.json()["reports"]
    assert rows[0]["pdfUrl"] == "https://pdf.dfcfw.com/pdf/H3_AP123_1.pdf"
    assert rows[1]["pdfUrl"] is None


def test_announcements_wrapped(client, monkeypatch):
    monkeypatch.setattr(svc, "announcements",
                        lambda code: [{"date": "2026-08-01", "title": "t", "type": "定期报告", "url": "u"}])
    r = client.get("/api/stock-insight/announcements", params={"symbol": "830799.BJ"})
    assert r.status_code == 200
    assert r.json() == {"announcements": [{"date": "2026-08-01", "title": "t", "type": "定期报告", "url": "u"}]}


def test_news_wrapped_with_chinese_fields(client, monkeypatch):
    rows = [{"新闻标题": "标题", "发布时间": "2026-08-01 10:00", "文章来源": "财联社", "新闻链接": "http://x"}]
    monkeypatch.setattr(svc, "stock_news", lambda code, limit=20: rows)
    r = client.get("/api/stock-insight/news", params={"symbol": "000001.SZ", "limit": 5})
    assert r.status_code == 200
    assert r.json() == {"news": rows}


def test_fund_flow_wrapped(client, monkeypatch):
    rows = [{"date": "2026-08-14", "main_net": 1.0, "small_net": -0.5,
             "mid_net": 0.2, "large_net": 0.6, "super_net": 0.4}]
    monkeypatch.setattr(svc, "stock_fund_flow_120d", lambda code: rows)
    r = client.get("/api/stock-insight/fund-flow", params={"symbol": "000001.SZ"})
    assert r.status_code == 200
    assert r.json() == {"rows": rows}


def test_dragon_tiger_shape(client, monkeypatch):
    payload = {"records": [{"date": "2026-08-01", "reason": "r", "net_buy": 1.0, "turnover": 5.0}],
               "seats": {"buy": [], "sell": []},
               "institution": {"buy_amt": 0.0, "sell_amt": 0.0, "net_amt": 0.0}}
    monkeypatch.setattr(svc, "dragon_tiger_board", lambda code: payload)
    r = client.get("/api/stock-insight/dragon-tiger", params={"symbol": "000001.SZ"})
    assert r.status_code == 200
    assert r.json() == payload


# ---------------------------------------------------------------------------
# 缓存行为
# ---------------------------------------------------------------------------

def test_cache_hits_service_once(client, monkeypatch):
    calls = []
    monkeypatch.setattr(svc, "announcements", lambda code: calls.append(code) or [])
    for _ in range(3):
        r = client.get("/api/stock-insight/announcements", params={"symbol": "000001.SZ"})
        assert r.status_code == 200
    assert calls == ["000001"]


def test_cache_keyed_by_symbol_and_params(client, monkeypatch):
    calls = []
    monkeypatch.setattr(svc, "stock_news", lambda code, limit=20: calls.append((code, limit)) or [])
    client.get("/api/stock-insight/news", params={"symbol": "000001.SZ", "limit": 5})
    client.get("/api/stock-insight/news", params={"symbol": "000001.SZ", "limit": 10})
    client.get("/api/stock-insight/news", params={"symbol": "600000.SH", "limit": 5})
    assert calls == [("000001", 5), ("000001", 10), ("600000", 5)]


def test_expired_cache_refetches(client, monkeypatch):
    calls = []
    monkeypatch.setattr(svc, "dragon_tiger_board",
                        lambda code: calls.append(code) or {"records": [], "seats": {"buy": [], "sell": []},
                                                            "institution": {}})
    monkeypatch.setattr(api, "_TTL_SLOW", -1)  # 立即过期
    client.get("/api/stock-insight/dragon-tiger", params={"symbol": "000001.SZ"})
    client.get("/api/stock-insight/dragon-tiger", params={"symbol": "000001.SZ"})
    assert calls == ["000001", "000001"]


# ---------------------------------------------------------------------------
# 失败兜底
# ---------------------------------------------------------------------------

def test_upstream_failure_returns_502(client, monkeypatch):
    def boom(code):
        raise RuntimeError("connection reset")

    monkeypatch.setattr(svc, "stock_fund_flow_120d", boom)
    r = client.get("/api/stock-insight/fund-flow", params={"symbol": "000001.SZ"})
    assert r.status_code == 502
    assert "资金流" in r.json()["detail"]


def test_failed_fetch_is_not_cached(client, monkeypatch):
    calls = []

    def flaky(code):
        calls.append(code)
        if len(calls) == 1:
            raise RuntimeError("boom")
        return []

    monkeypatch.setattr(svc, "announcements", flaky)
    assert client.get("/api/stock-insight/announcements", params={"symbol": "000001.SZ"}).status_code == 502
    assert client.get("/api/stock-insight/announcements", params={"symbol": "000001.SZ"}).status_code == 200
    assert calls == ["000001", "000001"]


# ---------------------------------------------------------------------------
# 代码转换
# ---------------------------------------------------------------------------

def test_symbol_to_code_and_secid():
    assert svc.symbol_to_code("000001.SZ") == "000001"
    assert svc.symbol_to_code("600000.SH") == "600000"
    assert svc.code_to_secid("600000") == "1.600000"
    assert svc.code_to_secid("000001") == "0.000001"
    assert svc.code_to_secid("830799") == "0.830799"
