"""Authenticated, batch watchlist news endpoints."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, HTTPException, Query, Request

from app.data_providers import news_registry
from app.data_providers.news_contract import NewsCategory, WatchlistNewsResponse
from app.services import watchlist, watchlist_news
from app.services.news_user_store import NewsUserStoreError

router = APIRouter(prefix="/api/watchlist/news", tags=["watchlist-news"])


def _current_symbols() -> list[str]:
    return [str(row.get("symbol", "")).strip().upper() for row in watchlist.list_symbols() if row.get("symbol")]


def _instrument_names(request: Request, symbols: list[str]) -> dict[str, str]:
    """Resolve display names from the shared read-only instrument catalog."""
    repo = getattr(request.app.state, "repo", None)
    if repo is None or not symbols:
        return {}
    try:
        return {
            str(symbol).upper(): str(name)
            for symbol, name in repo.get_name_map(symbols).items()
            if symbol and name
        }
    except Exception:  # missing catalog must not hide news
        return {}


def _service(request: Request) -> watchlist_news.WatchlistNewsService:
    service = getattr(request.app.state, "watchlist_news_service", None)
    if service is None:
        service = watchlist_news.WatchlistNewsService()
        request.app.state.watchlist_news_service = service
    return service


def _response(
    *,
    category: NewsCategory,
    result,
    selected_symbol: str | None,
    query: str | None,
    watchlist_count: int,
    name_by_symbol: dict[str, str] | None = None,
) -> WatchlistNewsResponse:
    as_of = max(
        (item.published_at for item in result.items if item.published_at is not None),
        default=None,
    )
    names = name_by_symbol or {}
    items = [
        item.model_copy(update={"name": names.get(item.symbol, item.name)})
        if item.symbol and not item.name and item.symbol in names
        else item
        for item in result.items
    ]
    return WatchlistNewsResponse(
        category=category,
        items=items,
        selected_symbol=selected_symbol,
        query=query,
        as_of=as_of,
        stale=result.stale,
        source_status=result.source_status,
        source_message=result.source_message,
        watchlist_count=watchlist_count,
        next_cursor=result.next_cursor,
    )


@router.get("/status")
def news_status(request: Request):
    preloader = getattr(request.app.state, "watchlist_news_preloader", None)
    return {
        "provider": news_registry.status(),
        "preloader": preloader.status() if preloader else {"running": False},
    }


@router.get("")
def list_news(
    request: Request,
    category: NewsCategory = Query(...),  # noqa: B008
    symbol: str | None = Query(None),
    q: str | None = Query(None, max_length=200),
    limit: int = Query(30, ge=1, le=100),
    cursor: str | None = Query(None, max_length=200),
) -> WatchlistNewsResponse:
    symbols = _current_symbols()
    selected_symbol = symbol.strip().upper() if symbol else None
    if selected_symbol and selected_symbol not in set(symbols):
        raise HTTPException(status_code=403, detail="只能查看当前账户自选股资讯")
    scoped_symbols = [selected_symbol] if selected_symbol else symbols
    now = datetime.now(UTC)
    try:
        result = _service(request).get_news(
            category=category,
            symbols=scoped_symbols,
            start_time=now - timedelta(days=watchlist_news.NEWS_LOOKBACK_DAYS),
            end_time=now,
            query=q,
            limit=limit,
            cursor=cursor,
        )
    except NewsUserStoreError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return _response(
        category=category,
        result=result,
        selected_symbol=selected_symbol,
        query=q,
        watchlist_count=len(symbols),
        name_by_symbol=_instrument_names(request, symbols),
    )


@router.get("/{item_id}")
def news_detail(
    item_id: str,
    request: Request,
    category: NewsCategory = Query(...),  # noqa: B008
):
    item = _service(request).get_item(
        item_id=item_id,
        category=category,
        symbols=_current_symbols(),
    )
    if item is None:
        raise HTTPException(status_code=404, detail="资讯不存在或不属于当前账户自选范围")
    names = _instrument_names(request, _current_symbols())
    if item.symbol and not item.name and item.symbol in names:
        return item.model_copy(update={"name": names[item.symbol]})
    return item
