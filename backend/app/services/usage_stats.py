"""访问统计 — 按日分桶的页面浏览 / API 调用 / 独立访客计数。

存储位置: data/usage_stats.json
visitors 只存 sha256(ip|day)[:16] 哈希, 不落原始 IP; 日内去重。
只保留最近 90 天的桶。脏数据由 daemon 线程每 30 秒落盘一次。
"""
from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

_TZ = ZoneInfo("Asia/Shanghai")
_KEEP_DAYS = 90
_FLUSH_INTERVAL_S = 30.0


class UsageStats:
    """线程安全的访问统计。测试可直接实例化 (不传 path 则读 settings.data_dir)。"""

    def __init__(self, path: Path | None = None) -> None:
        if path is None:
            from app.config import settings
            path = settings.data_dir / "usage_stats.json"
        self._path = path
        self._lock = threading.Lock()
        self._dirty = False
        self._data: dict = {"since": None, "days": {}}
        self._load()

    # ── 持久化 ──────────────────────────────────────────────

    def _load(self) -> None:
        if self._path.exists():
            try:
                value = json.loads(self._path.read_text(encoding="utf-8"))
                if isinstance(value, dict) and isinstance(value.get("days"), dict):
                    self._data = value
            except Exception as e:
                logger.warning("usage_stats.json malformed: %s", e)

    def flush(self) -> None:
        """有脏数据时落盘 (flush 线程与关停时调用)。"""
        with self._lock:
            if not self._dirty:
                return
            payload = {
                "since": self._data.get("since"),
                "days": self._data["days"],
            }
            self._dirty = False
        try:
            self._path.write_text(
                json.dumps(payload, ensure_ascii=False), encoding="utf-8"
            )
        except Exception as e:
            logger.warning("usage_stats flush failed: %s", e)
            with self._lock:
                self._dirty = True

    # ── 计数 ────────────────────────────────────────────────

    def _today(self) -> str:
        return datetime.now(_TZ).strftime("%Y-%m-%d")

    def record(self, ip: str, *, is_page: bool, is_api: bool) -> None:
        day = self._today()
        visitor = hashlib.sha256(f"{ip}|{day}".encode()).hexdigest()[:16]
        with self._lock:
            days = self._data["days"]
            bucket = days.setdefault(day, {"page_views": 0, "api_calls": 0, "visitors": []})
            if is_page:
                bucket["page_views"] += 1
            if is_api:
                bucket["api_calls"] += 1
            if visitor not in bucket["visitors"]:
                bucket["visitors"].append(visitor)
            if not self._data.get("since"):
                self._data["since"] = day
            self._prune_locked(day)
            self._dirty = True

    def _prune_locked(self, today: str) -> None:
        """只保留最近 _KEEP_DAYS 天的桶 (调用方须持锁)。"""
        days = self._data["days"]
        if len(days) <= _KEEP_DAYS:
            return
        for key in sorted(days)[: len(days) - _KEEP_DAYS]:
            days.pop(key, None)

    # ── 汇总 ────────────────────────────────────────────────

    def summary(self, days: int = 14) -> dict:
        today = self._today()
        with self._lock:
            all_days = sorted(self._data["days"])
            recent = [
                {"date": d, **self._day_counts(self._data["days"][d])}
                for d in all_days[-days:]
            ]
            total_page_views = sum(
                int(b.get("page_views", 0)) for b in self._data["days"].values()
            )
            since = self._data.get("since")
            today_bucket = self._data["days"].get(today)
        return {
            "since": since,
            "today": {"date": today, **self._day_counts(today_bucket)},
            "days": recent,
            "total_page_views": total_page_views,
        }

    @staticmethod
    def _day_counts(bucket: dict | None) -> dict:
        bucket = bucket or {}
        return {
            "page_views": int(bucket.get("page_views", 0)),
            "api_calls": int(bucket.get("api_calls", 0)),
            "visitors": len(bucket.get("visitors") or []),
        }


# ── 模块级单例 (惰性创建, 启动 30s 周期 flush 线程) ─────────

_instance: UsageStats | None = None
_instance_lock = threading.Lock()


def _flush_loop(stats: UsageStats) -> None:
    while True:
        time.sleep(_FLUSH_INTERVAL_S)
        stats.flush()


def get_usage_stats() -> UsageStats:
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = UsageStats()
                threading.Thread(
                    target=_flush_loop,
                    args=(_instance,),
                    name="usage-stats-flush",
                    daemon=True,
                ).start()
    return _instance
