"""访问统计服务与端点测试。"""
from __future__ import annotations

import json

from fastapi.testclient import TestClient

from app.main import app
from app.services.usage_stats import _KEEP_DAYS, UsageStats


def _stats(tmp_path) -> UsageStats:
    return UsageStats(path=tmp_path / "usage_stats.json")


def test_record_counts_and_dedupes_visitors_within_a_day(tmp_path):
    stats = _stats(tmp_path)

    stats.record("1.2.3.4", is_page=True, is_api=False)
    stats.record("1.2.3.4", is_page=True, is_api=False)  # 同 IP 同日只算 1 个访客
    stats.record("5.6.7.8", is_page=False, is_api=True)

    summary = stats.summary(14)
    assert summary["today"]["page_views"] == 2
    assert summary["today"]["api_calls"] == 1
    assert summary["today"]["visitors"] == 2
    assert summary["total_page_views"] == 2
    assert summary["since"] == summary["today"]["date"]


def test_record_keeps_only_recent_90_days(tmp_path, monkeypatch):
    stats = _stats(tmp_path)
    # 直接写入 100 个历史桶, 再 record 触发裁剪
    for i in range(100):
        stats._data["days"][f"2020-01-{i % 28 + 1:02d}x{i:03d}"] = {
            "page_views": 1, "api_calls": 0, "visitors": [],
        }
    monkeypatch.setattr(stats, "_today", lambda: "2020-12-31")
    stats.record("1.2.3.4", is_page=True, is_api=False)

    assert len(stats._data["days"]) == _KEEP_DAYS
    assert "2020-12-31" in stats._data["days"]


def test_flush_persists_and_reloads(tmp_path):
    stats = _stats(tmp_path)
    stats.record("1.2.3.4", is_page=True, is_api=False)
    stats.flush()

    raw = json.loads((tmp_path / "usage_stats.json").read_text(encoding="utf-8"))
    assert raw["since"] == stats.summary()["today"]["date"]

    reloaded = _stats(tmp_path)
    summary = reloaded.summary(14)
    assert summary["today"]["page_views"] == 1
    assert summary["today"]["visitors"] == 1


def test_summary_structure(tmp_path):
    stats = _stats(tmp_path)
    summary = stats.summary(14)

    assert summary["since"] is None
    assert summary["total_page_views"] == 0
    assert summary["days"] == []
    assert set(summary["today"]) == {"date", "page_views", "api_calls", "visitors"}
    assert summary["today"]["page_views"] == 0

    stats.record("1.2.3.4", is_page=True, is_api=True)
    summary = stats.summary(7)
    assert len(summary["days"]) == 1
    assert summary["days"][0]["date"] == summary["today"]["date"]
    assert summary["days"][0]["visitors"] == 1


def test_usage_stats_endpoint_requires_auth():
    response = TestClient(app).get("/api/settings/preferences/usage-stats")
    assert response.status_code in (401, 403)
