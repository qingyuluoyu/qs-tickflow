from fastapi.testclient import TestClient

from app.config import Settings
from app.main import app


def test_default_deployment_does_not_allow_arbitrary_cross_origin_requests():
    response = TestClient(app).get("/health", headers={"Origin": "https://evil.example"})

    assert "access-control-allow-origin" not in response.headers


def test_production_responses_include_browser_security_headers():
    response = TestClient(app, base_url="https://testserver").get("/health")

    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "SAMEORIGIN"
    assert response.headers["referrer-policy"] == "strict-origin-when-cross-origin"
    assert "frame-ancestors 'self'" in response.headers["content-security-policy"]
    assert response.headers["strict-transport-security"].startswith("max-age=")


def test_static_teaching_pages_allow_inline_scripts():
    """资产配置教学页/小游戏使用内联 <script>, CSP 需对它们单独放宽。"""
    client = TestClient(app, base_url="https://testserver")

    teaching = client.get("/asset-allocation.html")
    assert "script-src 'self' 'unsafe-inline'" in teaching.headers["content-security-policy"]

    game = client.get("/games/asset-allocation-game.html")
    assert "script-src 'self' 'unsafe-inline'" in game.headers["content-security-policy"]

    api = client.get("/health")
    assert "script-src 'self';" in api.headers["content-security-policy"]
    assert "unsafe-inline'; style-src" not in api.headers["content-security-policy"]


def test_cors_origins_are_explicitly_parsed_from_server_configuration():
    configured = Settings(
        _env_file=None,
        cors_origins="https://app.example.com, https://ops.example.com",
    )

    assert configured.cors_origin_list == [
        "https://app.example.com",
        "https://ops.example.com",
    ]
