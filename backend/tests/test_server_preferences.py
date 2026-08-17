import json
from concurrent.futures import ThreadPoolExecutor

from app.config import settings
from app.api import settings as settings_api
from app.services import preferences, server_preferences


def test_server_preferences_atomically_store_provider_and_migrate_legacy(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    legacy = tmp_path / "user_data" / "preferences.json"
    legacy.parent.mkdir(parents=True)
    legacy.write_text(
        json.dumps({"realtime_data_provider": "teajoin", "daily_data_provider": "teajoin"}),
        encoding="utf-8",
    )

    assert server_preferences.migrate_legacy() is True
    assert server_preferences.get_provider("realtime", "tickflow") == "teajoin"
    assert server_preferences.get_provider("daily", "tickflow") == "teajoin"
    assert server_preferences.migrate_legacy() is False


def test_server_preferences_concurrent_updates_do_not_overwrite_each_other(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", tmp_path)

    def save(index: int):
        return server_preferences.save({f"test_{index}": index})

    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(save, range(8)))

    stored = server_preferences.load()
    assert {stored[f"test_{index}"] for index in range(8)} == set(range(8))


def test_provider_selection_is_server_scoped_not_request_scoped(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(preferences, "_allowed_data_providers", lambda: {"tickflow", "teajoin"})
    server_preferences.save({"realtime_data_provider": "teajoin"})

    # A stale user preference must not make the process-wide background poller
    # switch provider when it has no request ContextVar.
    preferences.save({"realtime_data_provider": "tickflow"})

    assert preferences.get_realtime_data_provider() == "teajoin"


def test_settings_provider_update_writes_server_config(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", tmp_path)

    settings_api.update_data_providers(
        settings_api.DataProvidersIn(realtime_data_provider="teajoin")
    )

    assert server_preferences.load()["realtime_data_provider"] == "teajoin"
    assert not (tmp_path / "user_data" / "preferences.json").exists()


def test_realtime_runtime_scope_is_server_scoped(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    server_preferences.save({
        "realtime_quotes_enabled": True,
        "realtime_pull_stock": True,
        "realtime_pull_etf": True,
        "realtime_pull_index": False,
        "realtime_index_mode": "all",
        "realtime_index_symbols": ["000001.SH"],
    })
    preferences.save({
        "realtime_quotes_enabled": False,
        "realtime_pull_stock": False,
        "realtime_pull_index": True,
    })

    assert preferences.get_realtime_quotes_enabled() is True
    assert preferences.get_realtime_pull_stock() is True
    assert preferences.get_realtime_pull_etf() is True
    assert preferences.get_realtime_pull_index() is False
    assert preferences.get_realtime_index_mode() == "all"
    assert preferences.get_realtime_index_symbols() == ["000001.SH"]

    preferences.set_realtime_quote_scope({"realtime_pull_index": True, "realtime_index_mode": "core"})
    assert server_preferences.load()["realtime_pull_index"] is True
    assert server_preferences.load()["realtime_index_mode"] == "core"
