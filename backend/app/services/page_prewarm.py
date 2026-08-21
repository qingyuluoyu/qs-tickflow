"""通用页面预热 — 把用户常开页面的重计算提前跑好。

背景: RPS 轮动矩阵(概念分析/行业分析)按 (kind, level, 最新交易日) 缓存,
没人提前构建时第一个访问的用户要现场等矩阵计算。盘后管道会换最新交易日,
旧缓存键随即作废, 所以需要调度器定期预热, 而不是只在启动时跑一次。

看板(market_overview_preloader)、市场环境(daily_pipeline regime 步骤)、
复盘(定时 review job)各自已有常驻/调度机制, 这里只覆盖没有兜底的板块。
"""

import logging
import threading
import time

logger = logging.getLogger(__name__)

_prewarm_lock = threading.Lock()

# (kind, level) — 与前端 RpsRotationDialog 默认值对齐:
# 概念页 kind=concept/level=None, 行业页 kind=industry/level=2, days 默认 12
_RPS_TARGETS = (("concept", None), ("industry", 2))


def prewarm_common_pages(repo, quote_service=None) -> dict:
    """预热通用板块页面缓存。幂等: 命中缓存时秒回; 已有预热在跑则跳过。"""
    if not _prewarm_lock.acquire(blocking=False):
        logger.info("page prewarm skipped: already running")
        return {"skipped": True}
    t0 = time.perf_counter()
    done: list[str] = []
    failed: list[str] = []
    try:
        from app.services import rps_rotation

        for kind, level in _RPS_TARGETS:
            try:
                result = rps_rotation.build_rps_rotation(
                    repo, 12, kind, level, quote_service=quote_service
                )
                done.append(f"rps:{kind}:{result.get('concept_count', 0)}")
            except Exception:  # noqa: BLE001
                logger.exception("page prewarm failed: rps kind=%s level=%s", kind, level)
                failed.append(f"rps:{kind}")
        refreshed = _refresh_stale_ext_presets(repo)
        done.extend(refreshed)
        elapsed = time.perf_counter() - t0
        logger.info("page prewarm done in %.1fs: %s%s", elapsed, done, f" failed={failed}" if failed else "")
        return {"done": done, "failed": failed, "elapsed_s": round(elapsed, 1)}
    finally:
        _prewarm_lock.release()


def _refresh_stale_ext_presets(repo) -> list[str]:
    """内置概念/行业分类快照 (ext_gn_ths/ext_hy_ths) 隔日自动刷新。

    这两个预设历史上只在用户点「获取数据」时才拉取, 新用户首次打开
    概念/行业分析页会看到空表。这里在预热任务里检查: 数据日期早于今天
    (Asia/Shanghai) 就服务器端自动重拉, 用户永远不需要手动点。
    """
    import asyncio
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from app.services import ext_presets
    from app.services.ext_data import ExtConfigStore

    data_dir = repo.store.data_dir
    today = datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat()
    refreshed: list[str] = []
    for config_id in ("ext_gn_ths", "ext_hy_ths"):
        try:
            existing = ExtConfigStore(data_dir).get(config_id)
            synced = str(getattr(existing, "updated_at", "") or "")[:10]
            if existing is not None and synced >= today:
                continue
            n = asyncio.run(ext_presets.fetch_preset(config_id, data_dir))
            refreshed.append(f"ext:{config_id}:{n}")
        except Exception:  # noqa: BLE001
            logger.exception("page prewarm: ext preset %s refresh failed", config_id)
    return refreshed
