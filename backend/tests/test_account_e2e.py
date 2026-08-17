from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import polars as pl
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import auth, watchlist
from app.main import auth_middleware


def _test_app(data_dir: Path) -> FastAPI:
    app = FastAPI()
    app.middleware("http")(auth_middleware)
    app.include_router(auth.router)
    app.include_router(watchlist.router)
    app.state.repo = SimpleNamespace(
        store=SimpleNamespace(data_dir=data_dir),
        get_name_map=lambda _symbols: {},
    )
    app.state.account_directory = None
    app.state.monitor_runtime = None
    app.state.monitor_engine = None
    return app


def test_two_accounts_register_login_logout_and_keep_watchlists_isolated(monkeypatch, tmp_path: Path):
    from app.config import settings

    monkeypatch.setattr(settings, "data_dir", tmp_path)
    app = _test_app(tmp_path)

    with TestClient(app) as alice, TestClient(app) as bob:
        alice_entry = alice.post(
            "/api/auth/entry",
            json={"name": "Alice", "phone": "alice-phone", "password": "alice-password"},
        )
        bob_entry = bob.post(
            "/api/auth/entry",
            json={"name": "Bob", "phone": "bob-phone", "password": "bob-password"},
        )
        assert alice_entry.status_code == 200
        assert bob_entry.status_code == 200
        assert alice_entry.json()["created"] is True
        assert bob_entry.json()["created"] is True
        alice_id = alice_entry.json()["user"]["id"]
        bob_id = bob_entry.json()["user"]["id"]
        assert alice_id != bob_id

        assert alice.post("/api/watchlist", json={"symbol": "600000.SH"}).status_code == 200
        assert bob.post("/api/watchlist", json={"symbol": "000001.SZ"}).status_code == 200

        assert [row["symbol"] for row in alice.get("/api/watchlist").json()["symbols"]] == ["600000.SH"]
        assert [row["symbol"] for row in bob.get("/api/watchlist").json()["symbols"]] == ["000001.SZ"]

        with ThreadPoolExecutor(max_workers=2) as pool:
            alice_reads = pool.submit(
                lambda: [alice.get("/api/watchlist").json()["symbols"] for _ in range(10)],
            )
            bob_reads = pool.submit(
                lambda: [bob.get("/api/watchlist").json()["symbols"] for _ in range(10)],
            )
            assert all([row["symbol"] for row in rows] == ["600000.SH"] for rows in alice_reads.result())
            assert all([row["symbol"] for row in rows] == ["000001.SZ"] for rows in bob_reads.result())

        alice_path = tmp_path / "users" / alice_id / "user_data" / "watchlist.parquet"
        bob_path = tmp_path / "users" / bob_id / "user_data" / "watchlist.parquet"
        assert alice_path != bob_path
        assert pl.read_parquet(alice_path)["symbol"].to_list() == ["600000.SH"]
        assert pl.read_parquet(bob_path)["symbol"].to_list() == ["000001.SZ"]

        assert alice.post("/api/auth/logout").status_code == 200
        assert alice.get("/api/watchlist").status_code == 401
        assert bob.get("/api/watchlist").status_code == 200

        wrong_password = alice.post(
            "/api/auth/entry",
            json={"name": "Alice", "phone": "alice-phone", "password": "wrong-password"},
        )
        assert wrong_password.status_code == 401
        login_again = alice.post(
            "/api/auth/entry",
            json={"name": "Alice", "phone": "alice-phone", "password": "alice-password"},
        )
        assert login_again.status_code == 200
        assert login_again.json()["created"] is False
        assert login_again.json()["user"]["id"] == alice_id
        assert [row["symbol"] for row in alice.get("/api/watchlist").json()["symbols"]] == ["600000.SH"]
