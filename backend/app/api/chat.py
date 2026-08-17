"""Streaming Ask AI endpoint."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, model_validator

from app.services.chat import ChatStore, run_chat_tools_stream

router = APIRouter(prefix="/api/chat", tags=["chat"])
_CODE_RE = re.compile(r"^(?:\d{5,6}(?:\.[A-Z]{2})?|[A-Za-z][A-Za-z0-9.-]{0,15})$")


class ChatRequest(BaseModel):
    messages: list[dict[str, Any]] = Field(default_factory=list, max_length=40)
    context: str = Field(default="", max_length=12000)
    stock_code: str | None = Field(default=None, max_length=20)
    stock_name: str | None = Field(default=None, max_length=64)
    conversation_id: str = Field(default="default", min_length=1, max_length=80, pattern=r"^[A-Za-z0-9_.:-]+$")

    @model_validator(mode="after")
    def validate_payload(self) -> "ChatRequest":
        if self.stock_code:
            value = self.stock_code.strip().upper()
            if not _CODE_RE.fullmatch(value):
                raise ValueError("stock_code 格式无效")
            self.stock_code = value
        total = 0
        for item in self.messages:
            role = str(item.get("role") or "")
            if role not in {"user", "assistant"}:
                raise ValueError("messages role 只允许 user 或 assistant")
            content = str(item.get("content") or "")
            if len(content) > 8000:
                raise ValueError("单条消息不能超过 8000 字符")
            total += len(content)
        if total > 60000:
            raise ValueError("消息总长度不能超过 60000 字符")
        return self


@router.post("")
async def chat(request: Request, req: ChatRequest):
    repo = request.app.state.repo
    data_dir = repo.store.data_dir
    quote_service = getattr(request.app.state, "quote_service", None)
    depth_service = getattr(request.app.state, "depth_service", None)
    user_root = getattr(request.state, "user_data_root", None)
    store = ChatStore(data_dir, Path(user_root) if user_root else None)
    conversation_id = req.conversation_id
    messages = req.messages or store.load(conversation_id)
    # Save the user turn before streaming so a disconnected client still keeps
    # its input in the account-scoped transcript.
    if messages:
        store.save(messages, conversation_id)

    async def stream_gen():
        assistant_parts: list[str] = []
        async for event in run_chat_tools_stream(
            repo,
            data_dir,
            messages,
            req.context,
            req.stock_code,
            req.stock_name,
            quote_service,
            depth_service,
            user_root=user_root,
            conversation_id=conversation_id,
        ):
            if event.get("type") == "delta":
                assistant_parts.append(str(event.get("text") or ""))
            if event.get("type") == "done" and assistant_parts:
                store.save([*messages, {"role": "assistant", "content": "".join(assistant_parts)}], conversation_id)
            yield json.dumps(event, ensure_ascii=False, default=str) + "\n"

    return StreamingResponse(
        stream_gen(),
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
