"""WS /v1/stream?token= — per-connection auth, full-state resubscribe, Queue(100) drop-oldest."""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core.security import verify_ws_token
from app.infra.bus import Hub
from app.providers.stockbit.provider import get_provider

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Stream"])


def init_stream(hub: Hub):
    @router.websocket("/v1/stream")
    async def stream(ws: WebSocket):
        token = (
            ws.query_params.get("token")
            or ws.headers.get("x-api-key")
            or ws.headers.get("X-API-Key")
        )
        if not verify_ws_token(token):
            await ws.close(code=1008, reason="Invalid token")
            return
        try:
            await ws.accept()
        except Exception:
            return
        cid = str(id(ws))
        try:
            q = await hub.register(cid)
        except RuntimeError:
            await ws.close(code=1013, reason="Too many clients")
            return
        sender = asyncio.create_task(_sender(ws, q))
        prov = get_provider()
        try:
            while True:
                msg = await ws.receive_json()
                action = msg.get("action")
                if action == "subscribe":
                    symbols = [str(s).upper() for s in msg.get("symbols", []) if str(s).strip()]
                    kinds = set(msg.get("kinds", ["trades", "quotes", "books"]))
                    # validate wildcard rule
                    if "*" in symbols and any(k in kinds for k in ("quotes", "books")):
                        await ws.send_json(
                            {
                                "type": "error",
                                "message": "'*' only for trades (running_trade_batch) — use explicit symbols for quotes/books",
                            }
                        )
                        continue
                    try:
                        prov.live_feed().subscribe(set(symbols), kinds)
                    except ValueError as e:
                        await ws.send_json({"type": "error", "message": str(e)})
                        continue
                    await ws.send_json(
                        {"type": "subscribed", "symbols": symbols, "kinds": list(kinds)}
                    )
                elif action == "ping":
                    await ws.send_json({"type": "pong"})
                elif action == "unsubscribe":
                    await ws.send_json({"type": "unsubscribed"})
                else:
                    await ws.send_json({"type": "error", "message": f"unknown action: {action}"})
        except WebSocketDisconnect:
            pass
        except Exception as e:
            logger.debug(f"WS {cid} error: {e}")
        finally:
            sender.cancel()
            try:
                await sender
            except asyncio.CancelledError:
                pass
            await hub.unregister(cid)

    return router


async def _sender(ws: WebSocket, q: asyncio.Queue):
    try:
        while True:
            msg = await q.get()
            await ws.send_json(msg)
    except asyncio.CancelledError:
        pass
    except Exception:
        pass
