"""FastAPI entry — thin handlers, per-router auth, OpenAPI at /docs.

Domain never imports proto/ws_key; providers/stockbit is the only Stockbit boundary.
"""

from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()
load_dotenv(Path(__file__).resolve().parents[3] / ".env")

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.infra.bus import Hub
from app.infra.cache import BoundedCache

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

hub = Hub()
candles_cache = BoundedCache()

# will be set in lifespan
_auth_manager = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    # init transport + provider lazily after env loaded
    from app.providers.stockbit.auth import init_auth
    from app.providers.stockbit.provider import get_provider, init_provider
    from app.providers.stockbit.transport import init_transport

    bearer = os.getenv("STOCKBIT_BEARER_TOKEN", "").strip().strip('"').strip("'")
    refresh = os.getenv("STOCKBIT_REFRESH_TOKEN", "").strip().strip('"').strip("'")
    cookies_path = os.getenv("STOCKBIT_COOKIES_PATH", "./cookies.json")
    redis_url = os.getenv("REDIS_URL", "")

    async def _on_refresh(creds):
        from app.providers.stockbit.transport import get_transport

        try:
            get_transport().update_bearer(creds.bearer_token)
        except Exception:
            pass
        logger.info(f"Hot-swapped credentials user_id={creds.user_id} ttl={creds.ttl}s")

    try:
        init_transport(bearer=bearer)
    except Exception as e:
        logger.warning(f"transport init failed: {e}")
    try:
        init_provider(bearer=bearer)
    except Exception as e:
        logger.warning(f"provider init failed: {e}")

    auth = init_auth(
        bearer_token=bearer,
        refresh_token=refresh,
        cookies_path=cookies_path,
        on_refresh=_on_refresh,
    )
    auth.redis_url = redis_url
    global _auth_manager
    _auth_manager = auth
    try:
        await auth.start()
    except Exception as e:
        logger.warning(f"auth start failed (non-fatal): {e}")

    consumer_task = None
    ingest_mode = os.getenv("INGEST_MODE", "embedded")

    def _log_task_exit(name: str):
        def _cb(task: asyncio.Task):
            try:
                exc = task.exception()
            except asyncio.CancelledError:
                return
            if exc is not None:
                logger.error(f"{name} died: {exc!r}", exc_info=exc)

        return _cb

    if ingest_mode == "redis" and redis_url:
        from app.infra.bus import redis_consumer_task

        consumer_task = asyncio.create_task(redis_consumer_task(hub, redis_url))
        consumer_task.add_done_callback(_log_task_exit("redis_consumer"))
        logger.info(f"redis consumer started for {redis_url}")
    elif ingest_mode == "embedded":
        # Dev-only: local/no-Redis convenience. Production uses INGEST_MODE=redis
        # (Rust ingest-rs → Redis Streams → scaled api-py replicas).
        try:
            from app.providers.stockbit.embedded_ingest import run_embedded_ingest

            prov = get_provider()
            consumer_task = asyncio.create_task(run_embedded_ingest(prov, hub))
            consumer_task.add_done_callback(_log_task_exit("embedded_ingest"))
            logger.info("Embedded Stockbit WSS ingest task launched")
        except Exception as e:
            logger.warning(f"Could not launch embedded ingest: {e}")

    logger.info("lifespan startup complete — /v1/* ready, OpenAPI at /docs")
    yield
    logger.info("lifespan shutting down — draining hub")
    if consumer_task is not None:
        consumer_task.cancel()
        try:
            await consumer_task
        except asyncio.CancelledError:
            pass
    try:
        await auth.stop()
    except Exception:
        pass
    await asyncio.sleep(0.2)
    try:
        from app.providers.stockbit.transport import get_transport

        await get_transport().close()
    except Exception:
        pass
    logger.info("lifespan shutdown complete")


app = FastAPI(
    title="axiom-feed",
    version="0.1.0",
    description="Standalone market-data service — Stockbit WSS (prost+zlib) + REST (httpx.stream sliced). Provider-isolated.",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)

_raw_cors = os.getenv("CORS_ORIGINS", "*")
cors_origins = [o.strip() for o in _raw_cors.split(",") if o.strip()] or ["*"]
is_wildcard = "*" in cors_origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if is_wildcard else cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=False if is_wildcard else True,
)

# ── register routers ────────────────────────────────────────────────────
from app.api.v1 import analytics as analytics_mod
from app.api.v1 import books as books_mod
from app.api.v1 import brokers as brokers_mod
from app.api.v1 import charts as charts_mod
from app.api.v1 import estimates as estimates_mod
from app.api.v1 import fundamentals as fund_mod
from app.api.v1 import insider as insider_mod
from app.api.v1 import market as market_mod
from app.api.v1 import news as news_mod
from app.api.v1 import quotes as quotes_mod
from app.api.v1 import research as research_mod
from app.api.v1 import screeners as screeners_mod
from app.api.v1 import sectors as sectors_mod
from app.api.v1 import trades as trades_mod
from app.api.v1.candles import init_candles
from app.api.v1.health import init_health
from app.api.v1.stream import init_stream

app.include_router(init_health(hub, candles_cache))
app.include_router(init_candles(candles_cache))
app.include_router(init_stream(hub))
app.include_router(trades_mod.router)
app.include_router(quotes_mod.router)
app.include_router(books_mod.router)
app.include_router(charts_mod.router)
app.include_router(fund_mod.router)
app.include_router(sectors_mod.router)
app.include_router(brokers_mod.router)
app.include_router(market_mod.router)
app.include_router(estimates_mod.router)
app.include_router(insider_mod.router)
app.include_router(screeners_mod.router)
app.include_router(research_mod.router)
app.include_router(news_mod.router)
app.include_router(analytics_mod.router)


# health already mounted; fallback root
@app.get("/", tags=["Root"])
async def root():
    return {
        "name": "axiom-feed",
        "version": "0.1.0",
        "docs": "/docs",
        "health": "/v1/health",
        "ready": "/v1/ready",
        "endpoints": [
            "GET /v1/health",
            "GET /v1/ready",
            "GET /v1/candles/{symbol}?from=&to=&resolution=",
            "GET /v1/trades",
            "GET /v1/quotes",
            "GET /v1/books",
            "WS /v1/stream?token=",
        ],
    }


@app.exception_handler(Exception)
async def _unhandled(request, exc):
    logger.error(f"Unhandled {request.url.path}: {exc}", exc_info=True)
    return JSONResponse(status_code=500, content={"detail": "internal error"})
