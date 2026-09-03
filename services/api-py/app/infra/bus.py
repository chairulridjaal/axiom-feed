"""Bus — Redis Streams in prod, in-process asyncio.Queue in dev.

Spec: Queue(100) drop-oldest, Hub 500 clients → 429, messages_dropped counter.
"""

from __future__ import annotations

import asyncio
import logging
import os

import orjson

logger = logging.getLogger(__name__)

STREAM = "axiom.events"
CONSUMER_GROUP = "axiom-feed-api"
CONSUMER_NAME = "api-py-1"


async def _fanout_trade_batch(hub: Hub, evt: dict) -> None:
    payload = evt.get("payload") or {}
    trades = payload.get("trades") if isinstance(payload, dict) else None
    if not isinstance(trades, list):
        return
    ts = evt.get("ts")
    for t in trades:
        if not isinstance(t, dict):
            continue
        symbol = str(t.get("stock") or evt.get("symbol") or "").upper()
        if not symbol:
            continue
        await hub.publish({"kind": "trade", "symbol": symbol, "payload": t, "ts": ts})


class Hub:
    """Per-client Queue(100) drop-oldest with bounded clients."""

    def __init__(self, max_clients: int | None = None, queue_size: int | None = None):
        self.max_clients = int(max_clients or os.getenv("LIVE_MAX_CLIENTS", "500"))
        self.queue_size = int(queue_size or os.getenv("LIVE_QUEUE_PER_CLIENT", "100"))
        self._clients: dict[str, asyncio.Queue] = {}
        self._client_list: list[asyncio.Queue] = []
        self.messages_dropped = 0
        self.published = 0

    async def register(self, client_id: str) -> asyncio.Queue:
        if len(self._clients) >= self.max_clients:
            raise RuntimeError("too many clients")
        q: asyncio.Queue = asyncio.Queue(maxsize=self.queue_size)
        self._clients[client_id] = q
        self._client_list = list(self._clients.values())
        logger.info(f"Hub register {client_id} ({len(self._clients)}/{self.max_clients})")
        return q

    async def unregister(self, client_id: str):
        if self._clients.pop(client_id, None) is not None:
            self._client_list = list(self._clients.values())
            logger.info(f"Hub unregister {client_id} ({len(self._clients)} remaining)")

    async def publish(self, event: dict):
        self.published += 1
        clients = self._client_list
        if not clients:
            return
        for q in clients:
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                try:
                    q.get_nowait()
                except Exception:
                    pass
                try:
                    q.put_nowait(event)
                except Exception:
                    pass
                self.messages_dropped += 1

    def client_count(self) -> int:
        return len(self._clients)

    def stats(self) -> dict:
        return {
            "clients": len(self._clients),
            "max_clients": self.max_clients,
            "queue_size": self.queue_size,
            "messages_dropped": self.messages_dropped,
            "published": self.published,
        }


async def redis_consumer_task(hub: Hub, redis_url: str):
    """Consume axiom.events Streams and fan-out to Hub.

    Runs only when INGEST_MODE=redis. Uses a consumer group so multiple
    api-py replicas can scale horizontally. Falls back to plain XREAD if
    groups are unavailable (e.g., fresh Redis without group).
    """
    if not redis_url:
        logger.warning("redis_consumer disabled — REDIS_URL empty")
        return
    try:
        import redis.asyncio as aioredis  # type: ignore[import-untyped]
    except Exception as e:
        logger.warning(f"redis_consumer disabled — redis-py missing: {e}")
        return

    r = None
    last_id = "$"  # start from new messages; use "0-0" to replay after restart
    group_created = False
    try:
        r = aioredis.from_url(redis_url, decode_responses=True, socket_connect_timeout=5)
        # Try to create consumer group (idempotent)
        try:
            await r.xgroup_create(STREAM, CONSUMER_GROUP, id="$", mkstream=True)
            group_created = True
            logger.info(f"redis_consumer: group {CONSUMER_GROUP} ready on {STREAM}")
        except Exception as e:
            msg = str(e).lower()
            if "busygroup" in msg or "already exists" in msg:
                group_created = True
            else:
                logger.debug(f"xgroup_create skipped: {e}")

        while True:
            try:
                if group_created:
                    # XREADGROUP path — durable, at-least-once
                    resp = await r.xreadgroup(
                        CONSUMER_GROUP,
                        CONSUMER_NAME,
                        streams={STREAM: ">"},
                        count=100,
                        block=2000,
                    )
                else:
                    resp = await r.xread(streams={STREAM: last_id}, count=100, block=2000)
                if not resp:
                    continue
                for _stream, entries in resp:
                    ack_ids: list = []
                    for entry_id, fields in entries:  # type: ignore[assignment]
                        last_id = entry_id
                        raw: object = fields.get("payload")
                        if raw is None:
                            raw = fields.get("data")
                        if raw is None and fields:
                            raw = next(iter(fields.values()), None)
                        if not raw:
                            continue
                        try:
                            evt = (
                                orjson.loads(raw)
                                if isinstance(raw, (str, bytes, bytearray))
                                else raw
                            )
                        except Exception:
                            evt = {"raw": raw}
                        if isinstance(evt, dict):
                            if evt.get("kind") == "trade_batch":
                                await _fanout_trade_batch(hub, evt)
                            else:
                                await hub.publish(evt)
                            try:
                                from app.providers.stockbit.provider import get_provider

                                get_provider().live_feed().ingest_hub_event(evt)
                            except Exception:
                                pass
                        if group_created:
                            ack_ids.append(entry_id)
                    if group_created and ack_ids:
                        try:
                            await r.xack(STREAM, CONSUMER_GROUP, *ack_ids)
                        except Exception:
                            pass
                        # trim is done by producer MAXLEN ~1000
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning(f"redis_consumer loop error: {e}")
                await asyncio.sleep(2)
    finally:
        if r is not None:
            try:
                await r.close()
            except Exception:
                pass
        logger.info("redis_consumer stopped")
