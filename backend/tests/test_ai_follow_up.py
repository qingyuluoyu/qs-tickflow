from __future__ import annotations

from app.api import financials, market_recap as market_recap_api, stock_analysis
from app.services import financial_analyzer, market_recap, stock_analyzer


def test_stock_follow_up_prompt_carries_previous_answer_and_direct_question():
    prompt = stock_analyzer._build_user_prompt(
        kline_tail=[{"date": "2026-08-24", "close": 12.3}],
        fins={"metrics": [], "income": []},
        levels={},
        close=12.3,
        symbol="000001.SZ",
        focus="为什么你认为量价关系正在转弱？",
        previous_content="上一轮回答：量能较前五日均值下降。",
    )

    assert "上一轮分析回答" in prompt
    assert "量能较前五日均值下降" in prompt
    assert "用户追问: 为什么你认为量价关系正在转弱？" in prompt
    assert "不要重复生成整份报告" in prompt


def test_financial_follow_up_prompt_carries_previous_answer_and_direct_question():
    prompt = financial_analyzer._build_user_prompt(
        {"metrics": [{"roe": 12.5}]},
        "000001.SZ",
        "现金流和利润为什么背离？",
        previous_content="上一轮回答：净利润增长但经营现金流下降。",
    )

    assert "上一轮分析回答" in prompt
    assert "净利润增长但经营现金流下降" in prompt
    assert "用户追问: 现金流和利润为什么背离？" in prompt
    assert "不要重复生成整份报告" in prompt


def test_follow_up_context_is_part_of_both_analyze_request_contracts():
    stock_req = stock_analysis.AnalyzeRequest(
        symbol="000001.SZ",
        focus="继续解释",
        previous_content="上一轮回答",
    )
    financial_req = financials.AnalyzeRequest(
        symbol="000001.SZ",
        focus="继续解释",
        previous_content="上一轮回答",
    )

    assert stock_req.previous_content == "上一轮回答"
    assert financial_req.previous_content == "上一轮回答"


def test_market_recap_follow_up_prompt_carries_previous_answer_and_question():
    prompt = market_recap._build_user_prompt(
        {"as_of": "2026-08-24"},
        [],
        "为什么情绪分与上涨家数背离？",
        previous_content="上一轮复盘：情绪偏强，但上涨家数不足。",
    )

    assert "上一轮分析回答" in prompt
    assert "情绪偏强，但上涨家数不足" in prompt
    assert "用户追问: 为什么情绪分与上涨家数背离？" in prompt
    assert "不要重复生成整份报告" in prompt


def test_market_recap_request_contract_accepts_previous_content():
    req = market_recap_api.AnalyzeRequest(
        focus="继续解释",
        previous_content="上一轮复盘",
    )

    assert req.previous_content == "上一轮复盘"


def test_follow_up_prompt_bounds_long_previous_answer():
    previous = "开头结论" + ("分析内容" * 5000) + "结尾风险"

    prompt = financial_analyzer._build_user_prompt(
        {"metrics": [{"roe": 12.5}]},
        "000001.SZ",
        "请解释结论依据",
        previous_content=previous,
    )

    assert "开头结论" in prompt
    assert "结尾风险" in prompt
    assert "中间内容因长度已省略" in prompt
    assert len(prompt) < len(previous)
