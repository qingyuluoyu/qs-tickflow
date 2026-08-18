"""自选股服务(§6.1)。

存储:`data/user_data/watchlist.parquet`,字段 symbol + added_at + note。
"""
from __future__ import annotations

import contextlib
import logging
import os
import threading
import uuid
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path

import polars as pl

from app.config import settings
from app.tickflow.capabilities import Cap, CapabilitySet
from app.tickflow.client import get_client
from app.tickflow.rate_limits import chunked, resolve_limit

logger = logging.getLogger(__name__)


# A watchlist is a small user-owned document, but it is updated frequently by
# search clicks, OCR imports and batch imports.  Keep the existing Parquet
# format for compatibility while serialising read-modify-write operations.
# The thread lock covers requests handled by one worker; the sidecar lock file
# also serialises multiple backend workers/processes.
_PATH_LOCKS: dict[Path, threading.RLock] = {}
_PATH_LOCKS_GUARD = threading.Lock()


def _thread_lock(path: Path) -> threading.RLock:
    key = path.resolve()
    with _PATH_LOCKS_GUARD:
        lock = _PATH_LOCKS.get(key)
        if lock is None:
            lock = threading.RLock()
            _PATH_LOCKS[key] = lock
        return lock


@contextlib.contextmanager
def _exclusive_path_lock(path: Path) -> Iterator[None]:
    """Lock one watchlist across threads and backend worker processes."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with _thread_lock(path):
        lock_path = path.with_name(f".{path.name}.lock")
        with lock_path.open("a+b") as lock_file:
            # msvcrt.locking requires at least one byte in the locked region.
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

                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                lock_file.seek(0)
                if os.name == "nt":
                    import msvcrt

                    msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def _read(path: Path) -> pl.DataFrame:
    if not path.exists():
        return pl.DataFrame(schema={"symbol": pl.Utf8, "added_at": pl.Utf8, "note": pl.Utf8})
    return pl.read_parquet(path)


def _write_atomic(path: Path, frame: pl.DataFrame) -> None:
    """Write a complete Parquet file, then atomically publish it."""
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    try:
        frame.write_parquet(temporary)
        os.replace(temporary, path)
    finally:
        # If serialisation or replace failed, preserve the previous file and
        # remove only this operation's temporary artifact.
        with contextlib.suppress(FileNotFoundError):
            temporary.unlink()


def _path() -> Path:
    from app.services.user_context import personal_user_data_dir
    p = personal_user_data_dir(settings.data_dir) / "watchlist.parquet"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def list_symbols() -> list[dict]:
    p = _path()
    with _exclusive_path_lock(p):
        df = _read(p)
        return [] if df.is_empty() else df.to_dicts()


def add(symbol: str, note: str = "") -> list[dict]:
    p = _path()
    with _exclusive_path_lock(p):
        df = _read(p)
        # 已存在则先移除, 后面重新插入到最前面
        if not df.is_empty() and symbol in df["symbol"].to_list():
            df = df.filter(pl.col("symbol") != symbol)

        new_row = pl.DataFrame({
            "symbol": [symbol],
            "added_at": [datetime.utcnow().isoformat(timespec="seconds")],
            "note": [note],
        })
        out = pl.concat([new_row, df], how="diagonal_relaxed")
        _write_atomic(p, out)
        return out.to_dicts()


def add_many(symbols: list[str], note: str = "") -> tuple[list[dict], int]:
    """Add a batch with one locked read/write and return (rows, added_count)."""
    p = _path()
    with _exclusive_path_lock(p):
        df = _read(p)
        added = 0
        # Match the existing endpoint's ordering: each submitted symbol is
        # moved to the front, so the last submitted symbol is first.
        for symbol in symbols:
            if not df.is_empty() and symbol in df["symbol"].to_list():
                df = df.filter(pl.col("symbol") != symbol)
            else:
                added += 1
            new_row = pl.DataFrame({
                "symbol": [symbol],
                "added_at": [datetime.utcnow().isoformat(timespec="seconds")],
                "note": [note],
            })
            df = pl.concat([new_row, df], how="diagonal_relaxed")
        if symbols:
            _write_atomic(p, df)
        return ([] if df.is_empty() else df.to_dicts()), added


def remove(symbol: str) -> list[dict]:
    p = _path()
    with _exclusive_path_lock(p):
        df = _read(p)
        if df.is_empty():
            return []
        df = df.filter(pl.col("symbol") != symbol)
        _write_atomic(p, df)
        return df.to_dicts()


def move_to_top(symbol: str) -> list[dict]:
    p = _path()
    with _exclusive_path_lock(p):
        df = _read(p)
        if df.is_empty() or symbol not in df["symbol"].to_list():
            return df.to_dicts()
        target = df.filter(pl.col("symbol") == symbol)
        rest = df.filter(pl.col("symbol") != symbol)
        out = pl.concat([target, rest], how="diagonal_relaxed")
        _write_atomic(p, out)
        return out.to_dicts()


def clear() -> int:
    """清空自选列表。返回移除的数量。"""
    p = _path()
    with _exclusive_path_lock(p):
        df = _read(p)
        count = df.height
        if count > 0:
            _write_atomic(p, pl.DataFrame(schema={"symbol": pl.Utf8, "added_at": pl.Utf8, "note": pl.Utf8}))
        return count


def fetch_quotes(symbols: list[str], capset: CapabilitySet, timeout_s: float = 8.0) -> list[dict]:
    """拉取实时行情。

    优先用 quote.batch;否则降级为 quote.by_symbol 单股请求。
    timeout_s: 单批次请求超时(秒)，防止 API 卡死阻塞整个请求。
    """
    from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout

    if not symbols:
        return []

    tf = get_client()
    quotes: list[dict] = []

    # 走 batch
    if capset.has(Cap.QUOTE_BATCH):
        batch_size = resolve_limit(capset, Cap.QUOTE_BATCH, default_batch=50).batch
    elif capset.has(Cap.QUOTE_BY_SYMBOL):
        batch_size = resolve_limit(capset, Cap.QUOTE_BY_SYMBOL, default_batch=5).batch
    else:
        # 无任何实时行情能力(none/free 档走 free-api 服务器,不提供实时行情)
        # 提前返回空,避免发起注定失败的请求
        return []

    chunks = chunked(symbols, batch_size)

    # 用线程池为每个批次加超时保护
    pool = ThreadPoolExecutor(max_workers=1)
    for chunk in chunks:
        try:
            future = pool.submit(tf.quotes.get, symbols=chunk, as_dataframe=True)
            raw = future.result(timeout=timeout_s)
            if raw is None or len(raw) == 0:
                continue
            df = pl.from_pandas(raw)
            rename_map = {
                "last_price": "price",
                "ext.change_pct": "pct",
                "ext.name": "name",
            }
            df = df.rename({k: v for k, v in rename_map.items() if k in df.columns})
            quotes.extend(df.to_dicts())
        except FuturesTimeout:
            logger.warning("quote fetch timeout (%.1fs) for %d symbols", timeout_s, len(chunk))
            break  # 超时后不再尝试后续批次
        except Exception as e:  # noqa: BLE001
            logger.warning("quote fetch failed for %d symbols: %s", len(chunk), e)
    pool.shutdown(wait=False)

    return quotes
