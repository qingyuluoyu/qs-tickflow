"""User-owned persistence for generated news highlights."""
from __future__ import annotations

import contextlib
import json
import os
import threading
import uuid
from collections.abc import Iterator
from pathlib import Path

from app.config import settings
from app.data_providers.news_contract import NewsItem

_LOCKS: dict[Path, threading.RLock] = {}
_LOCKS_GUARD = threading.Lock()


class NewsUserStoreError(RuntimeError):
    pass


def _path() -> Path:
    from app.services.user_context import personal_user_data_dir

    return personal_user_data_dir(settings.data_dir) / "news_highlights.json"


def _thread_lock(path: Path) -> threading.RLock:
    key = path.resolve()
    with _LOCKS_GUARD:
        lock = _LOCKS.get(key)
        if lock is None:
            lock = threading.RLock()
            _LOCKS[key] = lock
        return lock


@contextlib.contextmanager
def _exclusive_lock(path: Path) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    with _thread_lock(path):
        lock_path = path.with_name(f".{path.name}.lock")
        with lock_path.open("a+b") as lock_file:
            lock_file.seek(0, os.SEEK_END)
            if lock_file.tell() == 0:
                lock_file.write(b"0")
                lock_file.flush()
            lock_file.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(lock_file.fileno(), msvcrt.LK_LOCK, 1)
            else:
                import fcntl

                fcntl.flock(lock_file, fcntl.LOCK_EX)
            try:
                yield
            finally:
                lock_file.seek(0)
                if os.name == "nt":
                    import msvcrt

                    msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(lock_file, fcntl.LOCK_UN)


def _write_atomic(path: Path, payload: dict) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )
        os.replace(temporary, path)
    finally:
        with contextlib.suppress(FileNotFoundError):
            temporary.unlink()


def load_highlights() -> list[NewsItem]:
    path = _path()
    if not path.exists():
        return []
    with _exclusive_lock(path):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            rows = payload.get("items", []) if isinstance(payload, dict) else None
            if not isinstance(rows, list):
                raise ValueError("items must be a list")
            return [NewsItem.model_validate(row) for row in rows]
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
            raise NewsUserStoreError("用户资讯摘要文件损坏") from exc


def save_highlights(items: list[NewsItem]) -> None:
    path = _path()
    payload = {
        "version": 1,
        "items": [item.model_dump(mode="json") for item in items],
    }
    with _exclusive_lock(path):
        _write_atomic(path, payload)


def filter_highlights(
    *,
    symbols: set[str],
    source_ids: set[str] | None = None,
    query: str | None = None,
    limit: int = 30,
) -> list[NewsItem]:
    if not 1 <= limit <= 100:
        raise ValueError("limit must be between 1 and 100")
    normalized_query = (query or "").strip().casefold()
    allowed_source_ids = source_ids or set()
    output: list[NewsItem] = []
    for item in load_highlights():
        if item.symbol and item.symbol not in symbols:
            continue
        if item.symbol is None and item.source_ids and item.source_ids[0] not in allowed_source_ids:
            continue
        if allowed_source_ids and not set(item.source_ids).intersection(allowed_source_ids):
            continue
        if normalized_query:
            haystack = " ".join(
                part.casefold()
                for part in (item.title, item.summary or "", item.content or "", item.source)
            )
            if normalized_query not in haystack:
                continue
        output.append(item)
        if len(output) >= limit:
            break
    return output
