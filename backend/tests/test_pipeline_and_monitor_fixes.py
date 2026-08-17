"""回归测试: 本轮修复的几处高风险行为(并发单飞 / 重任务槽 / sector fail-closed)。

均为纯逻辑, 不触网, 不依赖真实数据源。
"""
from __future__ import annotations

import polars as pl
import pytest

from app.api import data as data_api
from app.jobs import daily_pipeline
from app.services import pipeline_jobs, quote_service
from app.services.pipeline_jobs import JobStore
from app.services.quote_service import QuoteService
from app.strategy import monitor_rules
from app.strategy.monitor import MonitorRuleEngine

# ── JobStore 单飞 ────────────────────────────────────────────────────────

def test_create_singleflight_dedupes_pending_window(tmp_path):
    """两次快速 create() 在 pending 窗口内应复用同一 job(is_new=False)。"""
    store = JobStore(store_dir=tmp_path / "jobs")

    jid1, new1 = store.create()
    assert new1 is True

    # 尚未 start(), job 仍是 pending —— 旧实现会在此另起新 job(并发双跑根因)
    jid2, new2 = store.create()
    assert jid2 == jid1
    assert new2 is False

    # start() 后仍复用同一活跃 job
    store.start(jid1)
    jid3, new3 = store.create()
    assert jid3 == jid1
    assert new3 is False


def test_create_new_after_terminal(tmp_path):
    """job 终态(succeed/fail)后, create() 应给出新 job。"""
    store = JobStore(store_dir=tmp_path / "jobs")
    jid1, _ = store.create()
    store.start(jid1)
    store.succeed(jid1, {"ok": True})

    jid2, new2 = store.create()
    assert jid2 != jid1
    assert new2 is True


def test_job_store_persists_structured_error_detail(tmp_path):
    store = JobStore(store_dir=tmp_path / "jobs")
    job_id, _ = store.create()
    store.start(job_id)
    store.fail(job_id, "pipeline failed", details={"status": "waiting"})

    job = store.get(job_id)
    assert job is not None
    assert job["error"] == "pipeline failed"
    assert job["error_detail"] == {"status": "waiting"}


def test_run_slot_is_exclusive():
    """重任务执行槽同一时刻只允许一个持有者(防僵尸并发)。"""
    assert pipeline_jobs.try_acquire_run_slot() is True
    try:
        # 已被占用, 第二次获取失败
        assert pipeline_jobs.try_acquire_run_slot() is False
    finally:
        pipeline_jobs.release_run_slot()
    # 释放后可再次获取
    assert pipeline_jobs.try_acquire_run_slot() is True
    pipeline_jobs.release_run_slot()
    # 重复释放幂等, 不抛
    pipeline_jobs.release_run_slot()


def test_run_slot_rejects_when_another_process_holds_data_lock(monkeypatch):
    """跨进程数据锁不可用时，不得仅凭进程内锁启动写入任务。"""
    monkeypatch.setattr(pipeline_jobs, "_acquire_process_run_lock", lambda: None)

    assert pipeline_jobs.try_acquire_run_slot() is False


def test_acquire_process_lock_reclaims_lock_left_by_a_dead_process(tmp_path, monkeypatch):
    lock_dir = tmp_path / ".pipeline-run.lock"
    lock_dir.mkdir()
    (lock_dir / "pid").write_text("9424", encoding="ascii")

    monkeypatch.setattr(pipeline_jobs, "_process_lock_path", lambda: lock_dir)
    monkeypatch.setattr(pipeline_jobs, "_lock_owner_is_alive", lambda _path: False)

    acquired = pipeline_jobs._acquire_process_run_lock()

    assert acquired == lock_dir
    assert (lock_dir / "pid").read_text(encoding="ascii") == str(pipeline_jobs.os.getpid())
    (lock_dir / "pid").unlink()
    lock_dir.rmdir()


def test_lock_owner_check_reclaims_dead_pid_on_windows(tmp_path, monkeypatch):
    lock_dir = tmp_path / ".pipeline-run.lock"
    lock_dir.mkdir()
    (lock_dir / "pid").write_text("9424", encoding="ascii")

    monkeypatch.setattr(pipeline_jobs.os, "name", "nt")
    monkeypatch.setattr(pipeline_jobs, "_windows_pid_exists", lambda _pid: False)

    assert pipeline_jobs._lock_owner_is_alive(lock_dir) is False


def test_validate_market_snapshot_requires_target_daily_and_enriched_dates():
    """上游请求成功但目标交易日未落盘时，日终任务必须失败而非误报成功。"""
    class Repo:
        def latest_daily_date(self):
            return None

        def latest_enriched_date(self, asset_type="stock"):
            assert asset_type == "stock"
            return None

    errors = daily_pipeline.validate_market_snapshot_freshness(
        Repo(),
        target_date=__import__("datetime").date(2026, 8, 12),
        require_enriched=True,
    )

    assert errors == [
        "daily freshness: expected 2026-08-12, got none",
        "enriched freshness: expected 2026-08-12, got none",
    ]


def test_required_snapshot_date_uses_previous_weekday_before_close():
    """盘中不能要求尚未收盘的当日日线；周末应回退到上一个工作日。"""
    datetime = __import__("datetime").datetime
    assert daily_pipeline.required_market_snapshot_date(
        datetime(2026, 8, 13, 14, 27), {"hour": 15, "minute": 30}
    ).isoformat() == "2026-08-12"
    assert daily_pipeline.required_market_snapshot_date(
        datetime(2026, 8, 17, 10, 0), {"hour": 15, "minute": 30}
    ).isoformat() == "2026-08-14"


def test_snapshot_coverage_distinguishes_waiting_from_partial_data():
    target = __import__("datetime").date(2026, 8, 14)
    universe = ["000001.SZ", "600519.SH", "300001.SZ"]
    snapshot = pl.DataFrame({
        "symbol": ["000001.SZ", "600519.SH"],
        "date": [target, target],
    })

    partial = daily_pipeline.build_snapshot_coverage(
        target_date=target,
        universe=universe,
        provider_date=target,
        snapshot=snapshot,
    )
    assert partial["status"] == "partial"
    assert partial["available_rows"] == 2
    assert partial["missing_symbol_count"] == 1
    assert partial["missing_symbols"] == ["300001.SZ"]

    waiting = daily_pipeline.build_snapshot_coverage(
        target_date=target,
        universe=universe,
        provider_date=__import__("datetime").date(2026, 8, 13),
        snapshot=snapshot.filter(pl.col("date") < target),
    )
    assert waiting["status"] == "waiting"
    assert waiting["provider_date"] == "2026-08-13"
    assert waiting["missing_symbol_count"] == 3


def test_snapshot_coverage_separates_inactive_history_from_provider_gap():
    target = __import__("datetime").date(2026, 8, 14)
    metadata = pl.DataFrame({
        "symbol": ["000003.SZ", "600519.SH", "300001.SZ"],
        "name": ["某公司(退市)", "贵州茅台", "新公司"],
    })

    report = daily_pipeline.build_snapshot_coverage(
        target_date=target,
        universe=["000003.SZ", "600519.SH", "300001.SZ"],
        provider_date=target,
        snapshot=pl.DataFrame({
            "symbol": ["600519.SH"],
            "date": [target],
        }),
        instrument_metadata=metadata,
    )

    assert report["missing_symbol_count"] == 2
    assert report["inactive_symbol_count"] == 1
    assert report["inactive_symbols"] == ["000003.SZ"]
    assert report["unresolved_symbol_count"] == 1
    assert report["unresolved_symbols"] == ["300001.SZ"]


def test_snapshot_coverage_without_metadata_keeps_missing_symbols_unresolved():
    target = __import__("datetime").date(2026, 8, 14)
    report = daily_pipeline.build_snapshot_coverage(
        target_date=target,
        universe=["000003.SZ"],
        provider_date=target,
        snapshot=pl.DataFrame({"symbol": [], "date": []}),
    )

    assert report["inactive_symbol_count"] == 0
    assert report["unresolved_symbols"] == ["000003.SZ"]


def test_provider_reconciliation_distinguishes_recent_history_from_no_history():
    target = __import__("datetime").date(2026, 8, 14)
    daily = pl.DataFrame({
        "symbol": ["600984.SH", "300176.SZ", "300176.SZ"],
        "date": [
            __import__("datetime").date(2026, 8, 10),
            __import__("datetime").date(2026, 8, 12),
            __import__("datetime").date(2026, 8, 11),
        ],
    })

    report = daily_pipeline.build_provider_reconciliation(
        target_date=target,
        symbols=["600984.SH", "300176.SZ", "603221.SH"],
        daily=daily,
        instrument_metadata=pl.DataFrame({
            "symbol": ["600984.SH", "300176.SZ", "603221.SH"],
            "name": ["建设机械", "鸿特科技", "爱丽家居"],
        }),
    )

    assert report["status"] == "checked"
    assert report["symbols_with_target_date"] == 0
    assert report["symbols_with_recent_history"] == 2
    assert report["symbols_without_recent_history"] == 1
    assert report["details"] == [
        {
            "symbol": "300176.SZ",
            "name": "鸿特科技",
            "latest_available_date": "2026-08-12",
            "calendar_gap_days": 2,
            "status": "recent_history_no_target",
        },
        {
            "symbol": "600984.SH",
            "name": "建设机械",
            "latest_available_date": "2026-08-10",
            "calendar_gap_days": 4,
            "status": "recent_history_no_target",
        },
        {
            "symbol": "603221.SH",
            "name": "爱丽家居",
            "latest_available_date": None,
            "calendar_gap_days": None,
            "status": "no_history_available",
        },
    ]


def test_latest_pipeline_coverage_reads_success_and_failure_jobs():
    jobs = [
        {
            "id": "newer-failed",
            "status": "failed",
            "finished_at": "2026-08-14T10:00:00Z",
            "result": None,
            "error_detail": {
                "data_freshness": {"status": "waiting", "target_date": "2026-08-14"},
            },
        },
        {
            "id": "older-success",
            "status": "succeeded",
            "finished_at": "2026-08-14T09:00:00Z",
            "result": {
                "data_freshness": {"status": "partial", "target_date": "2026-08-14"},
            },
        },
    ]

    coverage = data_api._latest_pipeline_coverage(jobs)

    assert coverage == {
        "job_id": "newer-failed",
        "status": "failed",
        "finished_at": "2026-08-14T10:00:00Z",
        "data_freshness": {"status": "waiting", "target_date": "2026-08-14"},
    }


def test_market_data_health_distinguishes_inactive_from_unresolved_symbols():
    coverage = {
        "job_id": "job-1",
        "data_freshness": {
            "status": "partial",
            "source": "teajoin",
            "provider": "teajoin",
            "target_date": "2026-08-14",
            "provider_date": "2026-08-14",
            "requested_symbol_count": 5883,
            "available_symbol_count": 5540,
            "missing_symbol_count": 343,
            "inactive_symbol_count": 334,
            "unresolved_symbol_count": 9,
            "persisted_daily_date": "2026-08-14",
            "persisted_enriched_date": "2026-08-14",
            "persistence_status": "ready",
            "provider_reconciliation": {
                "status": "checked",
                "symbols_checked": 9,
                "symbols_with_recent_history": 2,
                "symbols_without_recent_history": 7,
            },
        },
    }

    health = data_api.build_market_data_health(coverage)

    assert health["status"] == "degraded"
    assert health["checks"]["coverage"] == {
        "requested": 5883,
        "available": 5540,
        "missing": 343,
        "inactive": 334,
        "unresolved": 9,
    }
    assert health["checks"]["provider_reconciliation"]["recent_history"] == 2


def test_market_data_health_is_ok_when_only_inactive_symbols_are_missing():
    health = data_api.build_market_data_health({
        "job_id": "job-2",
        "data_freshness": {
            "status": "partial",
            "source": "teajoin",
            "target_date": "2026-08-14",
            "provider_date": "2026-08-14",
            "requested_symbol_count": 10,
            "available_symbol_count": 8,
            "missing_symbol_count": 2,
            "inactive_symbol_count": 2,
            "unresolved_symbol_count": 0,
        },
    })

    assert health["status"] == "ok"
    assert health["coverage_status"] == "partial"


def test_market_data_health_is_unavailable_without_provider_snapshot():
    health = data_api.build_market_data_health({
        "data_freshness": {"status": "unavailable", "provider_date": None},
    })

    assert health["status"] == "unavailable"


def test_pipeline_stage_error_keeps_structured_freshness_details():
    error = daily_pipeline.PipelineStageError(
        ["daily freshness: expected 2026-08-14, got 2026-08-13"],
        data_freshness={
            "status": "waiting",
            "target_date": "2026-08-14",
            "provider_date": "2026-08-13",
            "missing_symbol_count": 3,
        },
    )

    details = daily_pipeline.pipeline_error_details(error)
    assert details["type"] == "pipeline_stage_error"
    assert details["stage_errors"] == error.errors
    assert details["data_freshness"]["status"] == "waiting"


def test_post_close_retry_times_are_bounded_and_after_pipeline_time():
    assert daily_pipeline.post_close_retry_times({"hour": 15, "minute": 30}) == [
        (16, 0),
        (16, 30),
        (17, 30),
    ]


# ── 监控 sector fail-closed ──────────────────────────────────────────────

def _base_price_rule(scope: str) -> dict:
    return {
        "id": "r_test",
        "name": "t",
        "type": "price",
        "conditions": [{"field": "close", "op": ">", "value": 10}],
        "logic": "and",
        "scope": scope,
    }


def test_validate_rejects_sector_scope():
    with pytest.raises(ValueError):
        monitor_rules.validate(_base_price_rule("sector"))


def test_validate_accepts_symbols_scope():
    rule = _base_price_rule("symbols")
    rule["symbols"] = ["600000.SH"]
    monitor_rules.validate(rule)  # 不应抛


def test_apply_scope_sector_fails_closed():
    """历史遗留 sector 规则在评估时应返回空(绝不退化为全市场)。"""
    df = pl.DataFrame({"symbol": ["600000.SH", "000001.SZ"], "close": [10.0, 20.0]})
    out = MonitorRuleEngine._apply_scope(df, {"id": "r_old", "scope": "sector"})
    assert out.is_empty()

    # 对照: scope=all 返回全量, symbols 过滤子集
    assert MonitorRuleEngine._apply_scope(df, {"scope": "all"}).height == 2
    picked = MonitorRuleEngine._apply_scope(
        df, {"scope": "symbols", "symbols": ["600000.SH"]}
    )
    assert picked.height == 1


def test_ladder_webhook_uses_chinese_title_without_brand(monkeypatch):
    calls = []

    class CaptureExecutor:
        def submit(self, fn, *args):
            calls.append((fn, args))

    monkeypatch.setattr(quote_service, "_WEBHOOK_EXECUTOR", CaptureExecutor())
    monkeypatch.setattr("app.services.preferences.get_feishu_webhook_url", lambda: "https://open.feishu.cn/open-apis/bot/v2/hook/test")
    monkeypatch.setattr("app.services.preferences.get_feishu_webhook_secret", lambda: "secret")
    monkeypatch.setattr("app.services.preferences.get_wecom_webhook_url", lambda: "wecom-key")

    engine = type("Engine", (), {
        "rules": {"r_ladder": {"webhook_channels": ["feishu", "wecom"]}},
    })()
    QuoteService._maybe_send_webhook(
        object.__new__(QuoteService),
        [{
            "rule_id": "r_ladder",
            "source": "ladder",
            "symbol": "600000.SH",
            "name": "浦发银行",
            "message": "炸板预警",
        }],
        engine,
    )

    assert [args[1] for _, args in calls] == ["连板梯队", "连板梯队"]
    assert all("TickFlow" not in args[1] for _, args in calls)


def test_review_webhooks_use_title_without_brand(monkeypatch):
    calls = []
    monkeypatch.setattr("app.services.preferences.get_review_push_channels", lambda: ["feishu", "wecom"])
    monkeypatch.setattr("app.services.preferences.get_feishu_webhook_url", lambda: "feishu-url")
    monkeypatch.setattr("app.services.preferences.get_feishu_webhook_secret", lambda: "secret")
    monkeypatch.setattr("app.services.preferences.get_wecom_webhook_url", lambda: "wecom-url")
    monkeypatch.setattr(
        "app.services.webhook_adapter.send_feishu_card",
        lambda *args: calls.append(("feishu", args)) or True,
    )
    monkeypatch.setattr(
        "app.services.webhook_adapter.send_wecom_markdown",
        lambda *args: calls.append(("wecom", args)) or True,
    )

    daily_pipeline._maybe_push_review("复盘正文", {"as_of": "2026-07-18"})

    assert [args[1] for _, args in calls] == ["每日复盘", "每日复盘"]
    assert all("TickFlow" not in args[1] for _, args in calls)
