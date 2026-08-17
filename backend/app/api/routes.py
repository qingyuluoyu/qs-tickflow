"""API 路由 — Phase 0 仅 /health 与 /api/capabilities。"""
from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app import __version__
from app.tickflow import client as tf_client
from app.tickflow.policy import detect_capabilities, tier_label

router = APIRouter()


@router.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "version": __version__,
        # 三态: none(无key/无效) / free(免费key) / api_key(付费档)
        "mode": tf_client.current_mode(),
    }


@router.get("/api/health")
def readiness(request: Request) -> JSONResponse:
    """Kubernetes/Docker readiness probe; it does not call an external provider."""
    checks = {
        "account_store": getattr(request.app.state, "account_store", None) is not None,
        "repository": getattr(request.app.state, "repo", None) is not None,
        "quote_service": getattr(request.app.state, "quote_service", None) is not None,
    }
    ready = all(checks.values())
    return JSONResponse(
        status_code=200 if ready else 503,
        content={"status": "ready" if ready else "starting", "checks": checks},
    )


@router.get("/api/capabilities")
def capabilities() -> dict:
    """前端用来决定哪些功能可用、哪些灰显。"""
    capset = detect_capabilities()
    return {
        "label": tier_label(),
        "capabilities": capset.to_dict(),
    }


@router.post("/api/capabilities/redetect")
def redetect() -> dict:
    """用户在设置页"重新检测"按钮。"""
    capset = detect_capabilities(force=True)
    return {
        "label": tier_label(),
        "capabilities": capset.to_dict(),
    }
