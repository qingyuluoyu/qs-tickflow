from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routes import router


def test_readiness_reports_starting_until_required_services_exist() -> None:
    test_app = FastAPI()
    test_app.include_router(router)

    response = TestClient(test_app).get("/api/health")

    assert response.status_code == 503
    assert response.json() == {
        "status": "starting",
        "checks": {
            "account_store": False,
            "repository": False,
            "quote_service": False,
        },
    }


def test_readiness_reports_ready_after_required_services_exist() -> None:
    test_app = FastAPI()
    test_app.state.account_store = object()
    test_app.state.repo = object()
    test_app.state.quote_service = object()
    test_app.include_router(router)

    response = TestClient(test_app).get("/api/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ready",
        "checks": {
            "account_store": True,
            "repository": True,
            "quote_service": True,
        },
    }
