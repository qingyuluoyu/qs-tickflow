"""多空辩论流式 API。"""
from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.services.debate import run_debate_stream

router = APIRouter(prefix="/api/debate", tags=["debate"])


class DebateRequest(BaseModel):
    code: str = Field(..., min_length=1, max_length=20, pattern=r"^(?:\d{5,6}(?:\.[A-Z]{2})?|[A-Za-z][A-Za-z0-9.-]{0,15})$")
    rounds: int = Field(default=1, ge=1, le=2)


@router.post("/stream")
async def debate_stream(request: Request, req: DebateRequest):
    repo = request.app.state.repo
    data_dir = repo.store.data_dir
    quote_service = getattr(request.app.state, "quote_service", None)

    async def stream_gen():
        async for chunk in run_debate_stream(repo, data_dir, req.code, req.rounds, quote_service):
            yield chunk + "\n"

    return StreamingResponse(
        stream_gen(),
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
