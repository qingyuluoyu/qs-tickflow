from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from app.services import watchlist
from app.services.user_context import UserIdentity, reset_current_user, set_current_user


def test_concurrent_adds_keep_every_symbol_and_leave_a_valid_parquet(monkeypatch, tmp_path: Path):
    """Rapid clicks/imports must not truncate or lose a user's watchlist."""
    from app.config import settings

    monkeypatch.setattr(settings, "data_dir", tmp_path)
    user_id = "00000000-0000-4000-8000-000000000001"
    user = UserIdentity(user_id, "Alice", "alice-phone")

    def add_one(index: int):
        token = set_current_user(user, tmp_path / "users" / user_id)
        try:
            return watchlist.add(f"{index:06d}.SH")
        finally:
            reset_current_user(token)

    with ThreadPoolExecutor(max_workers=12) as pool:
        list(pool.map(add_one, range(60)))

    token = set_current_user(user, tmp_path / "users" / user_id)
    try:
        symbols = watchlist.list_symbols()
    finally:
        reset_current_user(token)

    assert {row["symbol"] for row in symbols} == {f"{i:06d}.SH" for i in range(60)}
    assert len(symbols) == 60
