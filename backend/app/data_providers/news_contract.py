"""Provider-neutral contracts for the watchlist news radar."""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

NewsCategory = Literal["announcement", "public_news", "today_highlight"]
NewsSourceStatus = Literal["ok", "empty", "stale", "unavailable", "invalid"]


def _utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


class NewsItem(BaseModel):
    """A normalized public article; no user-specific fields are allowed here."""

    model_config = ConfigDict(extra="ignore")

    id: str
    category: NewsCategory
    symbol: str | None = None
    name: str | None = None
    title: str
    summary: str | None = None
    content: str | None = None
    url: str | None = None
    source: str
    published_at: datetime | None = None
    fetched_at: datetime
    data_version: str
    generated: bool = False
    source_ids: list[str] = Field(default_factory=list)

    @field_validator("id", "title", "source", "data_version", mode="before")
    @classmethod
    def _required_text(cls, value: object, info):
        text = str(value or "").strip()
        if not text:
            raise ValueError(f"{info.field_name} must not be empty")
        return text

    @field_validator("symbol", "name", "summary", "content", "url", mode="before")
    @classmethod
    def _optional_text(cls, value: object):
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    @field_validator("published_at", "fetched_at", mode="after")
    @classmethod
    def _normalize_timestamps(cls, value: datetime | None):
        return _utc(value)


class NewsFetchResult(BaseModel):
    """Provider response with explicit source state instead of silent empties."""

    model_config = ConfigDict(extra="forbid")

    items: list[NewsItem] = Field(default_factory=list)
    source_status: NewsSourceStatus
    source_message: str | None = None
    stale: bool = False
    next_cursor: str | None = None
    fetched_at: datetime

    @field_validator("fetched_at", mode="after")
    @classmethod
    def _normalize_fetched_at(cls, value: datetime):
        normalized = _utc(value)
        assert normalized is not None
        return normalized


class WatchlistNewsResponse(BaseModel):
    """HTTP response shape for the three watchlist news tabs."""

    category: NewsCategory
    items: list[NewsItem] = Field(default_factory=list)
    selected_symbol: str | None = None
    query: str | None = None
    as_of: datetime | None = None
    stale: bool = False
    source_status: NewsSourceStatus
    source_message: str | None = None
    watchlist_count: int = 0
    next_cursor: str | None = None

    @field_validator("as_of", mode="after")
    @classmethod
    def _normalize_as_of(cls, value: datetime | None):
        return _utc(value)
