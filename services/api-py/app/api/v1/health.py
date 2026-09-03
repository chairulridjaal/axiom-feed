import os
import time

from fastapi import APIRouter

from app.infra.bus import Hub
from app.infra.cache import BoundedCache
from app.providers.stockbit.auth import get_auth

router = APIRouter(tags=["Health"])
_started_at = time.monotonic()


def init_health(hub: Hub, cache: BoundedCache):
    @router.get("/v1/health")
    async def health():
        auth = get_auth()
        ah = auth.health() if auth else {"bearer_set": False}
        is_expired = ah.get("is_expired", False)
        bearer_set = ah.get("bearer_set", False)
        if auth is None:
            websocket_connected = True
            entitlement_active = True
        elif bearer_set:
            websocket_connected = not is_expired
            entitlement_active = websocket_connected
        else:
            websocket_connected = os.getenv("INGEST_MODE", "redis") == "embedded"
            entitlement_active = websocket_connected
        hub_stats = hub.stats()
        degraded_by_hub = hub_stats.get("messages_dropped", 0) > 5000
        status = "healthy" if (entitlement_active and not degraded_by_hub) else "degraded"
        return {
            "status": status,
            "uptime_seconds": time.monotonic() - _started_at,
            "websocket_connected": websocket_connected,
            "entitlement_active": entitlement_active,
            "degraded_reasons": (
                [] if status == "healthy" else (["hub_drop_high"] if degraded_by_hub else ["auth"])
            ),
            "hub": hub_stats,
            "cache": cache.stats(),
            "ingest": os.getenv("INGEST_MODE", "redis"),
            "auth": ah,
        }

    @router.get("/v1/ready")
    async def ready():
        auth = get_auth()
        ws_ok = True
        if auth and auth.creds:
            ws_ok = not auth.creds.is_expired
        redis_ok = True
        if os.getenv("INGEST_MODE", "redis") == "redis":
            redis_url = os.getenv("REDIS_URL", "")
            if redis_url:
                r = None
                try:
                    import redis.asyncio as aioredis

                    r = aioredis.from_url(redis_url, socket_connect_timeout=2)
                    await r.ping()
                except Exception:
                    redis_ok = False
                finally:
                    if r is not None:
                        try:
                            await r.aclose()
                        except Exception:
                            try:
                                await r.close()
                            except Exception:
                                pass
        ready_flag = ws_ok and redis_ok
        return {
            "ready": ready_flag,
            "ws_ok": ws_ok,
            "redis_ok": redis_ok,
            "auth": auth.health() if auth else {},
        }

    return router
