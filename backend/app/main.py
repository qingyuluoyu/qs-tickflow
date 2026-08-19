"""FastAPI 入口。"""
from __future__ import annotations

import logging
import threading
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app import __version__
from app.api import analysis, auth as auth_api, backtest, data, ext_data, financials, indices, intraday, kline, market_recap, monitor_rules, alerts, overview, pipeline, qingshu101, regime, rps, screener, settings as settings_api, signals, stock_analysis, stock_insight, strategy, watchlist, watchlist_news as watchlist_news_api
from app.api.routes import router as core_router
from app.config import settings
from app.jobs import daily_pipeline
from app.services.quote_service import QuoteService
from app.tickflow import client as tf_client
from app.tickflow.policy import detect_capabilities
from app.tickflow.repository import DataStore, KlineRepository

logging.basicConfig(
    level=settings.log_level,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(
        "TickFlow Stock Panel v%s starting (mode=%s)",
        __version__, tf_client.current_mode(),
    )

    # 首次启动: 若配置了 AUTH_PASSWORD 环境变量且未设过密码, 用它初始化。
    # 公网部署免 SSH 端口转发; 已设过密码则不覆盖 (改密码走 UI)。
    try:
        from app.services import auth as auth_service
        auth_service.bootstrap_from_env()
    except Exception as e:  # noqa: BLE001
        logger.warning("auth bootstrap failed: %s", e)

    # 本地账户数据库：迁移失败应阻止服务假启动，避免在未隔离状态下接受请求。
    from app.services.account_directory import AccountDirectoryCache
    from app.services.account_store import get_account_store
    account_store = get_account_store(settings.data_dir)
    account_directory = AccountDirectoryCache(
        account_store,
        refresh_interval=settings.account_directory_refresh_interval,
    )
    account_directory.start()
    app.state.account_store = account_store
    app.state.account_directory = account_directory

    # 数据层
    store = DataStore()
    repo = KlineRepository(store)
    app.state.datastore = store
    app.state.repo = repo
    # 在接受回测请求前固定 managed generation，避免首批并发 worker 各自创建版本。
    if settings.backtest_matrix_disk_cache_enabled:
        repo.get_matrix_data_generation("stock")
    # 指标异步预热标志: enriched 缓存在后台线程构建, 完成后置 True
    app.state.indicators_ready = False
    repo._on_warmup_done = lambda: setattr(app.state, "indicators_ready", True)  # noqa: SLF001

    # Polars 缓存预热 — enriched 的重计算 (107万行 compute_indicators) 推后台,
    # instruments/index/ETF 仍同步 (毫秒级)。应用立即 ready, 指标算完后自动替换。
    repo.refresh_cache(background=True)

    # 能力探测
    capset = detect_capabilities()
    app.state.capabilities = capset
    logger.info("ready; %d capabilities active", len(capset.all()))

    # 自定义数据源配置(可选): 失败只记录错误, 不影响 TickFlow 基准路径。
    try:
        from app.data_providers import custom as custom_sources
        custom_sources.load_all()
        logger.info("custom data sources loaded: %d", len(custom_sources.list_sources()))
    except Exception as e:  # noqa: BLE001
        logger.warning("custom data sources init failed: %s", e)

    # Prefer an operator-provided VibePublic API configuration; when it is
    # absent, the maintained Vibe-Research public-source adapter is used.
    # Invalid configuration remains fail-closed and must not affect
    # market-data startup.
    try:
        from app.data_providers import news_registry
        from app.services.watchlist_news import WatchlistNewsService

        news_registry.load()
        app.state.watchlist_news_service = WatchlistNewsService(
            provider=news_registry.get_provider(),
        )
        from app.services.watchlist_news_preloader import WatchlistNewsPreloader

        news_preloader = WatchlistNewsPreloader(
            account_store=account_store,
            shared_root=store.data_dir,
            service=app.state.watchlist_news_service,
            interval_s=300.0,
        )
        app.state.watchlist_news_preloader = news_preloader
        news_preloader.start()
        logger.info("watchlist news provider: %s", news_registry.status().get("name"))
    except Exception as e:  # noqa: BLE001
        logger.warning("VibePublic news provider init failed: %s", e)
        app.state.watchlist_news_service = None
        app.state.watchlist_news_preloader = None

    # Provider selection and background refresh settings are server-scoped.
    # Migrate only the old shared preferences file; never choose a provider
    # from an authenticated user's private workspace.
    try:
        from app.services import server_preferences
        server_preferences.migrate_legacy()
    except Exception as e:  # noqa: BLE001
        logger.warning("server preferences migration failed: %s", e)

    # 看板使用独立的快照预加载器: 盘中读取已配置 provider 的当日实时快照,
    # 收盘/休市读取 provider 的最近完整日线; 只有没有可用自定义行情能力时
    # 才回退新浪盘中快照。所有快照只保存在内存,不污染历史日K分区。
    try:
        from app.data_providers import custom as custom_sources
        from app.services import preferences
        from app.services.market_overview_preloader import (
            MarketOverviewPreloader,
            make_dashboard_failover_fetcher,
            make_dashboard_snapshot_fetcher,
            make_sina_intraday_snapshot_fetcher,
        )

        def _dashboard_stock_symbols() -> list[str]:
            instruments = repo.get_instruments()
            if instruments.is_empty() or "symbol" not in instruments.columns:
                return []
            return instruments.get_column("symbol").drop_nulls().unique().to_list()

        provider_fetcher = make_dashboard_snapshot_fetcher(daily_refresh_s=30.0)
        sina_fetcher = make_sina_intraday_snapshot_fetcher(
            _dashboard_stock_symbols,
            lambda: list(QuoteService.CORE_INDEX_SYMBOLS),
            repo,
            interval_s=30.0,
        )
        dashboard_failover_fetcher = make_dashboard_failover_fetcher(
            provider_fetcher,
            sina_fetcher,
        )

        def dashboard_fetcher():
            # Re-evaluate server-scoped provider settings on each cycle so a
            # provider change takes effect without restarting the process.
            realtime_provider = preferences.get_realtime_data_provider()
            daily_provider = preferences.get_daily_data_provider()
            custom_dashboard_data = (
                (
                    realtime_provider != "tickflow"
                    and custom_sources.provider_has_dataset(realtime_provider, "realtime")
                )
                or (
                    daily_provider != "tickflow"
                    and custom_sources.provider_has_dataset(daily_provider, "daily")
                )
            )
            return dashboard_failover_fetcher() if custom_dashboard_data else sina_fetcher()

        market_preloader = MarketOverviewPreloader(dashboard_fetcher, interval_s=30.0)
        app.state.market_overview_preloader = market_preloader
        market_preloader.start()
    except Exception as e:  # noqa: BLE001
        logger.warning("dashboard intraday preloader not started: %s", e)
        app.state.market_overview_preloader = None

    # 全局行情服务
    qs = QuoteService()
    app.state.quote_service = qs
    qs.set_repo(repo)
    qs.boot_check()

    # QuoteService 需要访问 strategy_monitor 等单例
    # 先创建 strategy_monitor，再注入 app.state
    from app.strategy.monitor import StrategyMonitorService
    strategy_monitor = StrategyMonitorService()
    app.state.strategy_monitor = strategy_monitor
    qs.set_app_state(app.state)

    # 五档盘口 sealed 服务(真假涨停/跌停, 独立旁路线)
    from app.services.depth_service import DepthService
    depth_service = DepthService()
    depth_service.set_repo(repo)
    depth_service.set_app_state(app.state)
    app.state.depth_service = depth_service

    # 启动调度器(若 enriched 数据为空,首次启动可手动 POST /api/pipeline/run)
    try:
        daily_pipeline.set_app_state(app.state)  # 供 depth_finalize job 访问 depth_service
        scheduler = daily_pipeline.start_scheduler(repo, capset)
        app.state.scheduler = scheduler
    except Exception as e:  # noqa: BLE001
        logger.warning("scheduler not started: %s", e)
        app.state.scheduler = None

    # depth sealed: 启动补跑(当天文件不存在) + 盘中轮询(有能力时)
    try:
        depth_service.boot_check()
        depth_service.start_polling()
    except Exception as e:  # noqa: BLE001
        logger.warning("depth_service init failed: %s", e)

    # 企业微信智能机器人长连接(可选通道, 失败不阻断启动)
    try:
        from app.services.wecom_bot_service import WecomBotService
        wecom_bot_service = WecomBotService()
        wecom_bot_service.set_app_state(app.state)
        app.state.wecom_bot_service = wecom_bot_service
        wecom_bot_service.boot_check()
    except Exception as e:  # noqa: BLE001
        logger.warning("wecom_bot_service init failed: %s", e)

    # 内置扩展表 (概念/行业): 先创建 config (含拉取配置), 默认开启定时拉取。
    # 必须在 pull_scheduler.refresh() 之前执行, 否则全新部署时 scheduler 读不到
    # 刚创建的预设, 定时任务不会启动。
    try:
        from app.services.ext_presets import ensure_builtin_presets
        await ensure_builtin_presets(store.data_dir)
    except Exception as e:  # noqa: BLE001
        logger.warning("内置扩展表初始化失败 (不影响启动): %s", e)

    # 扩展数据定时拉取: 在预设配置就绪后启动, 自动调度 enabled 的预设。
    from app.services.ext_pull import pull_scheduler
    pull_scheduler.start()
    pull_scheduler.refresh(store.data_dir)
    app.state.pull_scheduler = pull_scheduler

    # 财务数据 (需 Expert 套餐): 默认保留手动同步；服务器配置
    # financial_schedule.enabled=true 时额外启用非阻塞周期预处理。
    from app.services.financial_sync import financial_scheduler
    from app.services import server_preferences
    financial_schedule = server_preferences.get_financial_schedule()
    financial_scheduler.start(
        store.data_dir,
        capset,
        auto_schedule=bool(financial_schedule.get("enabled", False)),
        schedule_interval_days=int(financial_schedule.get("interval_days", 7) or 7),
    )
    app.state.financial_scheduler = financial_scheduler

    # 策略引擎
    from app.strategy.engine import StrategyEngine
    from app.strategy import config as strategy_config
    from app.strategy.monitor import StrategyMonitorService
    from app.services.screener import ScreenerService

    _screener_svc = ScreenerService(repo)
    _etf_screener_svc = ScreenerService(repo, asset_type="etf")
    strategy_dirs = [
        Path(__file__).resolve().parent / "strategy" / "builtin",
        store.data_dir / "strategies" / "custom",
        store.data_dir / "strategies" / "ai",
        store.data_dir / "strategies" / "composite",
    ]
    strategy_engine = StrategyEngine(
        strategy_dirs=strategy_dirs,
        override_loader=lambda sid: strategy_config.load_override(store.data_dir, sid),
    )
    app.state.strategy_engine = strategy_engine
    logger.info("strategy engine loaded: %d strategies", len(strategy_engine.list_strategies()))

    matrix_prewarm_lock = threading.Lock()
    matrix_prewarm_running = False

    def _schedule_matrix_cache_prewarm() -> None:
        nonlocal matrix_prewarm_running
        if (
            not settings.backtest_matrix_disk_cache_enabled
            or not settings.backtest_matrix_cache_prewarm
        ):
            return
        with matrix_prewarm_lock:
            if matrix_prewarm_running:
                logger.info("matrix cache prewarm already in progress, skip")
                return
            matrix_prewarm_running = True

        def _prewarm() -> None:
            nonlocal matrix_prewarm_running
            try:
                latest = repo.latest_enriched_date("stock")
                if latest is None:
                    logger.info("matrix cache prewarm skipped: no stock enriched data")
                    return
                from app.backtest.engine import BacktestEngine
                from app.backtest.strategy import prewarm_matrix_cache

                result = prewarm_matrix_cache(
                    BacktestEngine(repo),
                    strategy_engine,
                    asset_type="stock",
                    latest_date=latest,
                    years=settings.backtest_matrix_cache_prewarm_years,
                )
                logger.info("matrix cache prewarm done: %s", result)
            except Exception:  # noqa: BLE001
                logger.exception("matrix cache prewarm failed")
            finally:
                with matrix_prewarm_lock:
                    matrix_prewarm_running = False

        threading.Thread(
            target=_prewarm,
            name="matrix-cache-prewarm",
            daemon=True,
        ).start()

    repo._on_refresh_done = _schedule_matrix_cache_prewarm  # noqa: SLF001
    if repo.enriched_ready:
        _schedule_matrix_cache_prewarm()

    # 通用监控规则引擎: 启动时 reload 规则到内存态 (修复重启后告警失效)
    from app.strategy.monitor import MonitorRuleEngine
    from app.strategy import monitor_rules as mr_store
    from app.services import preferences
    from app.services.sector_monitor import SectorMonitorService
    monitor_engine = MonitorRuleEngine()
    sector_monitor_service = SectorMonitorService(repo)
    monitor_engine.set_strategy_engine(strategy_engine)
    monitor_engine.set_data_dir(store.data_dir)
    monitor_engine.set_sector_monitor_service(sector_monitor_service)
    # 复用 ScreenerService 的历史窗口加载器 (三级缓存, 启动预计算命中 ~0ms),
    # 让声明 filter_history 的策略 (如反包) 也能在实时监控里跑选股 → 盘中触发通知。
    monitor_engine.set_history_loader(_screener_svc._load_enriched_history)
    # ETF 版历史加载器: asset_type=etf 的 strategy 型规则用 (读 kline_etf_enriched)。
    monitor_engine.set_history_loader_etf(_etf_screener_svc._load_enriched_history)

    # 自动迁移: 把旧 strategy_monitor_ids 同步为 type=strategy 规则 (统一到监控页)
    try:
        if preferences.get_strategy_monitor_enabled():
            ids = preferences.get_strategy_monitor_ids()
            if ids:
                names = {s["id"]: s["name"] for s in strategy_engine.list_strategies()}
                mr_store.migrate_strategy_monitors(store.data_dir, ids, names)
                logger.info("strategy monitor migrated: %d strategies", len(ids))
    except Exception as e:  # noqa: BLE001
        logger.warning("strategy monitor migration failed: %s", e)

    try:
        if account_store.has_users():
            # Account mode keeps monitor rules in per-user workspaces. Do not
            # load the legacy shared rule directory into a global engine.
            monitor_engine.clear()
            logger.info("account mode: shared monitor engine disabled")
        else:
            rules = mr_store.load_all(store.data_dir)
            monitor_engine.set_rules(rules)
            logger.info("monitor engine loaded: %d rules", monitor_engine.rule_count)
    except Exception as e:  # noqa: BLE001
        logger.warning("monitor engine load failed: %s", e)
    app.state.monitor_engine = monitor_engine
    app.state.sector_monitor_service = sector_monitor_service

    # Account mode uses one monitor engine per user.  Market data remains
    # shared, while rule state, strategy overrides, cooldowns and alert files
    # stay under each account workspace.  The quote poller refreshes this
    # registry periodically so newly registered accounts are picked up
    # without a process restart.
    from app.services.monitor_runtime import AccountMonitorRuntime
    monitor_runtime = AccountMonitorRuntime(
        account_store=account_store,
        shared_root=store.data_dir,
        builtin_dir=Path(__file__).resolve().parent / "strategy" / "builtin",
        history_loader=_screener_svc._load_enriched_history,
        history_loader_etf=_etf_screener_svc._load_enriched_history,
        sector_monitor_service=sector_monitor_service,
        repo=repo,
    )
    try:
        monitor_runtime.start()
    except Exception:  # noqa: BLE001
        logger.exception("account monitor runtime initial refresh failed")
    app.state.monitor_runtime = monitor_runtime

    yield

    dashboard_preloader = getattr(app.state, "market_overview_preloader", None)
    if dashboard_preloader:
        dashboard_preloader.stop()
    qs = getattr(app.state, "quote_service", None)
    if qs:
        qs.stop()
    monitor_runtime = getattr(app.state, "monitor_runtime", None)
    if monitor_runtime:
        monitor_runtime.stop()
    directory = getattr(app.state, "account_directory", None)
    if directory:
        directory.stop()
    ps = getattr(app.state, "pull_scheduler", None)
    if ps:
        ps.stop()
    fsc = getattr(app.state, "financial_scheduler", None)
    if fsc:
        fsc.stop()
    if app.state.scheduler:
        app.state.scheduler.shutdown(wait=False)
    try:
        from app.data_providers import custom as custom_sources
        custom_sources.close_all()
    except Exception:  # noqa: BLE001
        logger.warning("custom data source shutdown failed", exc_info=True)
    news_preloader = getattr(app.state, "watchlist_news_preloader", None)
    if news_preloader:
        news_preloader.stop()
    try:
        from app.data_providers import news_registry
        news_registry.close()
    except Exception:  # noqa: BLE001
        logger.warning("VibePublic news provider shutdown failed", exc_info=True)
    dsvc = getattr(app.state, "depth_service", None)
    if dsvc:
        dsvc.stop_polling()
    wbot = getattr(app.state, "wecom_bot_service", None)
    if wbot:
        wbot.stop()
    logger.info("shutdown")


app = FastAPI(
    title="TickFlow Stock Panel",
    version=__version__,
    description="A 股选股 + 回测面板 — TickFlow 适配",
    lifespan=lifespan,
)

# The product uses HttpOnly cookies, so wildcard browser origins are unsafe and
# cannot authenticate correctly. Same-origin needs no CORS headers; operators
# may opt into a bounded list for a separately hosted trusted frontend.
# 出口带宽是部署瓶颈: 文本资源 (JS/CSS/JSON) gzip 后体积降 60-80%。
# minimum_size 避免小响应压缩开销; streaming/SSE 响应不受影响 (starlette 自动跳过)。
app.add_middleware(GZipMiddleware, minimum_size=1024)

if settings.cors_origin_list:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
    )


@app.middleware("http")
async def security_headers_middleware(request: Request, call_next):
    """Apply browser hardening without changing API payload contracts."""
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    if request.url.path not in {"/docs", "/redoc", "/openapi.json"}:
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; base-uri 'self'; frame-ancestors 'none'; "
            "object-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data: blob:; font-src 'self' data:; "
            "connect-src 'self' ws: wss:; form-action 'self'"
        )
    if request.url.path.startswith(("/api/auth/", "/api/qingshu101/")):
        response.headers["Cache-Control"] = "no-store"
    elif request.url.path.startswith("/assets/"):
        # vite 产物文件名带内容 hash, 可永久缓存 — 带宽受限环境的关键优化
        response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    if auth_api._is_https(request):  # noqa: SLF001 - shared trusted-proxy policy
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response


@app.middleware("http")
async def request_trace_middleware(request: Request, call_next):
    """Attach a non-sensitive request id to every response for operations logs."""
    supplied = request.headers.get("x-request-id", "")
    request_id = supplied if supplied and len(supplied) <= 64 and supplied.replace("-", "").isalnum() else uuid.uuid4().hex
    request.state.request_id = request_id
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    return response


# ================================================================
# 访问认证中间件
# ================================================================
# 拦截所有 /api/ 请求, 三种状态:
#   1. 未设密码 + 本机/内网 → 放行(让本机用户访问面板 + 调 /api/auth/setup 设密码)
#   2. 未设密码 + 公网       → 拒绝(403, 防裸奔也防抢占; 引导本机设密码)
#   3. 已设密码              → 检查 session, 无效则 401(前端跳登录)
# 白名单: /api/auth/* (设密码/登录本身)、/health 等探活。
_AUTH_WHITELIST_PREFIX = ("/api/auth/", "/api/qingshu101/")
_AUTH_WHITELIST_EXACT = ("/health", "/api/health", "/openapi.json", "/docs", "/redoc")


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    path = request.url.path
    # 仅 /api/ 走认证; 静态资源(前端页面/assets)放行, 由前端处理跳转
    if not path.startswith("/api/"):
        return await call_next(request)
    # 白名单放行(设密码/登录/探活本身不拦)
    if path.startswith(_AUTH_WHITELIST_PREFIX) or path in _AUTH_WHITELIST_EXACT:
        return await call_next(request)

    # 账户模式：每个会话必须解析到明确的 user_id，之后所有个人存储
    # 通过 request.state.user_data_root / ContextVar 使用对应工作区。
    from app.services.account_store import get_account_store
    from app.services.user_context import reset_current_user, set_current_user

    token = request.cookies.get(auth_api.COOKIE_NAME)
    account_store = get_account_store(settings.data_dir)
    user = account_store.user_for_token(token)
    if user is None:
        return JSONResponse(status_code=401, content={"detail": "未登录或会话已过期", "code": "AUTH_REQUIRED"})

    user_root = account_store.ensure_workspace(user.id)
    request.state.user = user
    request.state.user_data_root = user_root
    tokens = set_current_user(user, user_root)
    try:
        return await call_next(request)
    finally:
        reset_current_user(tokens)


# 路由
app.include_router(core_router)
app.include_router(auth_api.router)
app.include_router(qingshu101.router)
app.include_router(kline.router)
app.include_router(watchlist.router)
app.include_router(watchlist_news_api.router)
app.include_router(screener.router)
app.include_router(backtest.router)
app.include_router(intraday.router)
app.include_router(indices.router)
app.include_router(overview.router)
app.include_router(regime.router)
app.include_router(analysis.router)
app.include_router(pipeline.router)
app.include_router(data.router)
app.include_router(ext_data.router)
app.include_router(financials.router)
app.include_router(stock_analysis.router)
app.include_router(market_recap.router)
app.include_router(settings_api.router)
app.include_router(strategy.router)
app.include_router(signals.router)
app.include_router(monitor_rules.router)
app.include_router(alerts.router)
app.include_router(rps.router)
app.include_router(stock_insight.router)


# 能力门控异常 → 403(而非默认 500)
# 业务代码用 capset.require(Cap.X) 断言能力,缺失时抛 CapabilityDenied;
# 若不注册 handler 会冒泡成 500 Internal Server Error,对前端不友好且语义错误。
from app.tickflow.capabilities import CapabilityDenied


@app.exception_handler(CapabilityDenied)
async def capability_denied_handler(request: Request, exc: CapabilityDenied) -> JSONResponse:
    return JSONResponse(
        status_code=403,
        content={"detail": str(exc), "suggestion": exc.suggestion},
    )

# 生产期静态文件(前端 dist)
_static = Path(settings.static_dir)
if _static.exists():
    if (_static / "assets").exists():
        app.mount("/assets", StaticFiles(directory=_static / "assets"), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa_fallback(full_path: str):  # noqa: ARG001
        """所有未匹配路径回退到 index.html — React Router 接管。

        dist 根目录下的真实文件 (brand-icon.png / favicon.svg 等) 优先直接返回。
        index.html 禁止缓存 (Cache-Control: no-store), 确保浏览器每次拿到
        最新版本引用的 JS/CSS 文件名 (assets 带 hash, 可长缓存)。
        """
        if full_path:
            candidate = (_static / full_path).resolve()
            if candidate.is_file() and candidate.is_relative_to(_static.resolve()):
                return FileResponse(candidate)
        index = _static / "index.html"
        if index.exists():
            return FileResponse(
                index,
                headers={"Cache-Control": "no-store, must-revalidate"},
            )
        return {"error": "frontend not built"}
