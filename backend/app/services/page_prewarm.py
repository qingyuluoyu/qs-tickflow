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
        elapsed = time.perf_counter() - t0
        logger.info("page prewarm done in %.1fs: %s%s", elapsed, done, f" failed={failed}" if failed else "")
        return {"done": done, "failed": failed, "elapsed_s": round(elapsed, 1)}
    finally:
        _prewarm_lock.release()
