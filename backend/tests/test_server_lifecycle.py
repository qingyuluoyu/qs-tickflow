from __future__ import annotations

import asyncio

from starlette.requests import Request
from starlette.responses import Response

from app.main import request_trace_middleware


def _request(headers: list[tuple[bytes, bytes]] | None = None) -> Request:
    return Request({
        "type": "http",
        "method": "GET",
        "path": "/health",
        "raw_path": b"/health",
        "query_string": b"",
        "headers": headers or [],
        "scheme": "http",
        "client": ("127.0.0.1", 1234),
        "server": ("testserver", 80),
        "root_path": "",
    })


def test_request_trace_id_is_generated_and_propagated():
    request = _request()

    async def next_handler(_request):
        return Response("ok")

    response = asyncio.run(request_trace_middleware(request, next_handler))

    assert response.headers["x-request-id"]
    assert response.headers["x-request-id"] == request.state.request_id


def test_request_trace_id_accepts_safe_correlation_header():
    request = _request([(b"x-request-id", b"release-check-01")])

    async def next_handler(_request):
        return Response("ok")

    response = asyncio.run(request_trace_middleware(request, next_handler))

    assert response.headers["x-request-id"] == "release-check-01"
