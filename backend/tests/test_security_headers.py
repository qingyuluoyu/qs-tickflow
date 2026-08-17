from fastapi.testclient import TestClient

from app.config import Settings
from app.main import app


def test_default_deployment_does_not_allow_arbitrary_cross_origin_requests():
    response = TestClient(app).get("/health", headers={"Origin": "https://evil.example"})

    assert "access-control-allow-origin" not in response.headers


def test_production_responses_include_browser_security_headers():
    response = TestClient(app, base_url="https://testserver").get("/health")

    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["referrer-policy"] == "strict-origin-when-cross-origin"
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
    assert response.headers["strict-transport-security"].startswith("max-age=")


def test_cors_origins_are_explicitly_parsed_from_server_configuration():
    configured = Settings(
        _env_file=None,
        cors_origins="https://app.example.com, https://ops.example.com",
    )

    assert configured.cors_origin_list == [
        "https://app.example.com",
        "https://ops.example.com",
    ]
