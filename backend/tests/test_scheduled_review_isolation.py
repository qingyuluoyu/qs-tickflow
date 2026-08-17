from __future__ import annotations

from pathlib import Path

import pytest

from app.services.user_context import UserIdentity, current_user


class _RecordingScheduler:
    def __init__(self):
        self.calls: list[dict] = []

    def add_job(self, func, *, args, **kwargs):
        self.calls.append({"func": func, "args": args, **kwargs})


def test_each_scheduled_review_has_an_owner_specific_job_id():
    from app.jobs.daily_pipeline import _register_review_job, review_job_id

    scheduler = _RecordingScheduler()
    repo = object()
    alice = UserIdentity(id="11111111-1111-1111-1111-111111111111", name="Alice", phone="alice")
    bob = UserIdentity(id="22222222-2222-2222-2222-222222222222", name="Bob", phone="bob")
    alice_root = Path("C:/data/users/alice")
    bob_root = Path("C:/data/users/bob")

    _register_review_job(scheduler, repo, alice, alice_root, 16, 0)
    _register_review_job(scheduler, repo, bob, bob_root, 16, 30)

    assert [call["id"] for call in scheduler.calls] == [review_job_id(alice.id), review_job_id(bob.id)]
    assert scheduler.calls[0]["args"] == [repo, alice, alice_root]
    assert scheduler.calls[1]["args"] == [repo, bob, bob_root]


@pytest.mark.asyncio
async def test_scheduled_review_binds_the_owner_before_saving_a_report(monkeypatch, tmp_path: Path):
    from app.jobs import daily_pipeline
    from app.services import ai_provider, market_recap_reports

    alice = UserIdentity(id="11111111-1111-1111-1111-111111111111", name="Alice", phone="alice")
    saved_for: list[str | None] = []

    async def fake_stream(*_args):
        return "private review", {"as_of": "2026-08-17"}

    monkeypatch.setattr(ai_provider, "ai_configured", lambda: True)
    monkeypatch.setattr(daily_pipeline, "_stream_review_with_retry", fake_stream)
    monkeypatch.setattr(daily_pipeline, "_get_app_state", lambda: None)
    monkeypatch.setattr(
        market_recap_reports,
        "save_report",
        lambda _report: saved_for.append(current_user().id if current_user() else None),
    )

    await daily_pipeline._run_scheduled_review(object(), alice, tmp_path / "users" / alice.id)

    assert saved_for == [alice.id]
    assert current_user() is None
