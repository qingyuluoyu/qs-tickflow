from app.services import preferences


def test_data_provider_defaults_prefer_teajoin_when_it_is_available(monkeypatch):
    monkeypatch.setattr(preferences, "load", lambda: {})
    monkeypatch.setattr(preferences, "_allowed_data_providers", lambda: {"tickflow", "teajoin"})

    assert preferences.get_daily_data_provider() == "teajoin"
    assert preferences.get_adj_factor_provider() == "same_as_daily"
    assert preferences.get_minute_data_provider() == "teajoin"
    assert preferences.get_realtime_data_provider() == "teajoin"
    assert preferences.get_financial_provider() == "teajoin"
