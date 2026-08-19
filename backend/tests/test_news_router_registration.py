from __future__ import annotations


def test_watchlist_news_router_is_registered_on_main_app():
    from app.main import app

    paths = {route.path for route in app.routes}
    assert "/api/watchlist/news" in paths
    assert "/api/watchlist/news/{item_id}" in paths
    assert "/api/watchlist/news/status" in paths
