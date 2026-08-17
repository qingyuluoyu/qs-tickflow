from __future__ import annotations

import sqlite3
from pathlib import Path

from app.config import settings
from app.services import preferences
from app.services.account_store import get_account_store
from app.services.user_context import reset_current_user, set_current_user


def _create_user(data_dir: Path, name: str, phone: str):
    store = get_account_store(data_dir)
    result = store.enter(name, phone, f"{phone}-password")
    assert result is not None
    return store, result.user


def _bind(store, user):
    return set_current_user(user, store.workspace(user.id))


def test_preferences_are_stored_by_user_id_in_the_account_database(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    store, alice = _create_user(tmp_path, "Alice", "alice-phone")
    _, bob = _create_user(tmp_path, "Bob", "bob-phone")

    tokens = _bind(store, alice)
    try:
        preferences.save({"indices_nav_pinned": False, "minute_sync_days": 9})
    finally:
        reset_current_user(tokens)
    tokens = _bind(store, bob)
    try:
        assert preferences.load() == {}
        preferences.save({"indices_nav_pinned": True, "minute_sync_days": 3})
        bob_preferences = preferences.load()
    finally:
        reset_current_user(tokens)

    tokens = _bind(store, alice)
    try:
        alice_preferences = preferences.load()
    finally:
        reset_current_user(tokens)

    assert bob_preferences["minute_sync_days"] == 3
    assert alice_preferences["minute_sync_days"] == 9
    with sqlite3.connect(tmp_path / "accounts.sqlite3") as conn:
        rows = conn.execute("SELECT user_id FROM user_preferences ORDER BY user_id").fetchall()
    assert {row[0] for row in rows} == {alice.id, bob.id}


def test_existing_personal_preferences_are_copied_once_without_removing_the_file(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    store, alice = _create_user(tmp_path, "Alice", "alice-phone")
    legacy_path = store.workspace(alice.id) / "user_data" / "preferences.json"
    legacy_path.write_text('{"minute_sync_days": 7}', encoding="utf-8")

    tokens = _bind(store, alice)
    try:
        loaded = preferences.load()
    finally:
        reset_current_user(tokens)

    assert loaded["minute_sync_days"] == 7
    assert legacy_path.exists()
    with sqlite3.connect(tmp_path / "accounts.sqlite3") as conn:
        stored = conn.execute(
            "SELECT value_json FROM user_preferences WHERE user_id = ?", (alice.id,)
        ).fetchone()
    assert stored is not None
