"""DEV-ONLY embedded live feed (INGEST_MODE=embedded, no Redis/Rust needed).

Production path is Rust ingest-rs → Redis Streams → scaled api-py replicas
(INGEST_MODE=redis). This module is a local convenience only — never production.
"""

import asyncio
import logging
import os
import zlib

logger = logging.getLogger(__name__)

# Set EMBEDDED_DEBUG=1 for per-frame wire diagnostics (tag byte, lengths).
_DEBUG = os.getenv("EMBEDDED_DEBUG", "0").strip() not in ("", "0", "false", "False")


def _try_zlib(raw: bytes) -> bytes | None:
    try:
        out = zlib.decompress(raw)
        return out if out and len(out) > 8 else None
    except Exception:
        return None


def _try_deflate(raw: bytes) -> bytes | None:
    try:
        out = zlib.decompress(raw, -15)
        return out if out and len(out) > 8 else None
    except Exception:
        return None


def decompress(raw: bytes) -> bytes:
    """Mirror services/ingest-rs/src/decode.rs::decompress.

    zlib-wrapped frames (0x78 header) try zlib first, otherwise raw deflate
    first; truncated-stream suffix variant last. Returns raw untouched when
    nothing validates, so plain (already-decompressed) protobuf still parses.
    """
    if not raw:
        return raw
    is_zlib = len(raw) >= 2 and raw[0] == 0x78
    if is_zlib:
        for attempt in (_try_zlib(raw), _try_deflate(raw)):
            if attempt is not None:
                return attempt
    else:
        first = _try_deflate(raw)
        if first is not None:
            return first
        suffixed = _try_deflate(raw + b"\x00\x00\xff\xff")
        if suffixed is not None:
            return suffixed
        fallback = _try_zlib(raw)
        if fallback is not None:
            return fallback
    return raw


async def run_embedded_ingest(provider, hub):
    """Connect directly to Stockbit WSS in Python, decode, and feed into live provider + hub."""
    from typing import Any

    import google.protobuf.timestamp_pb2  # noqa: F401 — registers timestamp.proto in the pool
    import websockets
    from websockets.typing import Subprotocol

    from app.providers.stockbit.auth import get_auth
    from app.providers.stockbit.generated import datafeed_pb2 as pb_module
    from app.providers.stockbit.mapping import (
        map_legacy_orderbook_msg,
        map_liveprice_to_quote,
        map_orderbook_body_to_book,
        map_running_trade_to_domain,
    )

    pb: Any = pb_module

    auth = get_auth()
    if not auth or not auth.creds:
        logger.info("Embedded ingest: waiting for auth credentials...")
        for _ in range(20):
            await asyncio.sleep(0.5)
            if auth and auth.creds:
                break
        if not auth or not auth.creds:
            logger.warning("Embedded ingest: no credentials, idle")
            return

    creds = auth.creds
    ws_url = os.getenv("STOCKBIT_WS_URL", "wss://wss-trading.stockbit.com/ws")
    headers = {
        "Origin": "https://stockbit.com",
        "Authorization": f"Bearer {creds.bearer_token}",
    }

    logger.info(f"Embedded WSS connecting to {ws_url} for user {creds.user_id}...")
    while True:
        try:
            async with websockets.connect(
                ws_url,
                additional_headers=headers,
                user_agent_header="Mozilla/5.0",
                subprotocols=[Subprotocol("web")],
                ping_interval=None,
                compression=None,
                max_size=16 * 1024 * 1024,
            ) as ws:
                logger.info("Embedded WSS connected to Stockbit live feed")

                # Send full subscription
                sub = pb.WebsocketRequest()
                sub.user_id = creds.user_id
                sub.key = creds.ws_key
                sub.access_token = creds.bearer_token
                sub.channel.running_trade_batch.extend(["*"])
                sub.channel.watchlist.extend(["*"])

                # explicit symbols
                seed = [
                    s.strip().upper()
                    for s in os.getenv("SUBSCRIBE_SYMBOLS", "BBCA,TLKM,IHSG,BBRI,BMRI").split(",")
                    if s.strip()
                ]
                sub.channel.liveprice.extend(sorted(seed))
                sub.channel.order_book.extend(sorted(seed))

                sub_bytes = sub.SerializeToString()
                await ws.send(sub_bytes)
                logger.info(
                    f"Embedded WSS sent full subscription (trades=* seed={seed} bytes={len(sub_bytes)} head={sub_bytes[:24].hex()})"
                )

                # Ping task
                async def ping_loop():
                    while True:
                        await asyncio.sleep(25)
                        p = pb.WebsocketRequest()
                        p.ping.timestamp.GetCurrentTime()
                        await ws.send(p.SerializeToString())

                p_task = asyncio.create_task(ping_loop())
                frames = 0
                kinds: dict[str, int] = {}
                try:
                    async for raw_msg in ws:
                        frames += 1
                        if isinstance(raw_msg, str):
                            logger.info(
                                f"Embedded WSS text frame len={len(raw_msg)} head={raw_msg[:160]!r}"
                            )
                            continue
                        if isinstance(raw_msg, bytes):
                            if _DEBUG or frames <= 5:
                                logger.info(
                                    f"Embedded WSS raw frame #{frames} len={len(raw_msg)} "
                                    f"head={raw_msg[:16].hex()} b0={raw_msg[0] if raw_msg else -1}"
                                )
                            data = decompress(raw_msg)
                            wrapper = pb.WebsocketWrapMessageChannel()
                            try:
                                wrapper.ParseFromString(data)
                                which = wrapper.WhichOneof("message_channel")
                                if _DEBUG or frames <= 5:
                                    logger.info(
                                        f"Embedded WSS decoded #{frames} which={which} "
                                        f"raw_len={len(raw_msg)} dec_len={len(data)}"
                                    )
                                kinds[str(which)] = kinds.get(str(which), 0) + 1
                                if frames % 100 == 0:
                                    logger.info(f"Embedded WSS stats frames={frames} kinds={kinds}")
                                if which == "ping":
                                    continue
                                if which == "error":
                                    err = wrapper.error
                                    logger.error(
                                        f"Embedded WSS server error code={err.code} message={err.message!r}"
                                    )
                                    continue
                                if which == "running_trade_batch":
                                    batch_events: list[dict] = []
                                    for t in wrapper.running_trade_batch.batch:
                                        trade = map_running_trade_to_domain(t)
                                        provider.live_feed().ingest_trade(trade)
                                        batch_events.append(
                                            {
                                                "kind": "trade",
                                                "symbol": trade.symbol,
                                                "payload": {
                                                    "stock": trade.symbol,
                                                    "price": float(trade.price),
                                                    "volume": trade.volume,
                                                    "side": str(
                                                        trade.side.value
                                                        if hasattr(trade.side, "value")
                                                        else trade.side
                                                    ),
                                                    "trade_number": trade.seq,
                                                },
                                            }
                                        )
                                    if batch_events:
                                        await hub.publish_batch(batch_events)
                                elif which == "running_trade":
                                    trade = map_running_trade_to_domain(wrapper.running_trade)
                                    provider.live_feed().ingest_trade(trade)
                                    await hub.publish(
                                        {
                                            "kind": "trade",
                                            "symbol": trade.symbol,
                                            "payload": {
                                                "stock": trade.symbol,
                                                "price": float(trade.price),
                                                "volume": trade.volume,
                                                "side": str(
                                                    trade.side.value
                                                    if hasattr(trade.side, "value")
                                                    else trade.side
                                                ),
                                                "trade_number": trade.seq,
                                            },
                                        }
                                    )
                                elif which == "liveprice":
                                    q = map_liveprice_to_quote(wrapper.liveprice)
                                    provider.live_feed().ingest_quote(q)
                                    await hub.publish(
                                        {
                                            "kind": "quote",
                                            "symbol": q.symbol,
                                            "payload": {
                                                "stock": q.symbol,
                                                "price": float(q.last),
                                                "open": float(q.open) if q.open else None,
                                                "high": float(q.high) if q.high else None,
                                                "low": float(q.low) if q.low else None,
                                            },
                                        }
                                    )
                                elif which == "orderbook":
                                    b = map_legacy_orderbook_msg(wrapper.orderbook)
                                    if b:
                                        provider.live_feed().ingest_book(b)
                                        await hub.publish(
                                            {
                                                "kind": "book",
                                                "symbol": b.symbol,
                                                "payload": {
                                                    "bids": [
                                                        {"price": float(lv.price), "lot": lv.lots}
                                                        for lv in b.bids
                                                    ],
                                                    "offers": [
                                                        {"price": float(lv.price), "lot": lv.lots}
                                                        for lv in b.asks
                                                    ],
                                                },
                                            }
                                        )
                                elif which == "orderbook_body":
                                    ob = wrapper.orderbook_body
                                    book = map_orderbook_body_to_book(
                                        ob.stock_symbol, ob.bid, ob.offer
                                    )
                                    provider.live_feed().ingest_book(book)
                                    await hub.publish(
                                        {
                                            "kind": "book",
                                            "symbol": book.symbol,
                                            "payload": {
                                                "bids": [
                                                    {"price": float(lv.price), "lot": lv.lots}
                                                    for lv in book.bids
                                                ],
                                                "offers": [
                                                    {"price": float(lv.price), "lot": lv.lots}
                                                    for lv in book.asks
                                                ],
                                            },
                                        }
                                    )
                                elif which is None:
                                    logger.warning(
                                        f"Embedded WSS empty wrapper raw_len={len(raw_msg)} "
                                        f"dec_len={len(data)} head={data[:16].hex() if data else ''}"
                                    )
                            except Exception:
                                logger.exception(
                                    f"Embedded WSS decode/map failed raw_len={len(raw_msg)} "
                                    f"dec_len={len(data)} head={data[:16].hex() if data else ''}"
                                )
                finally:
                    p_task.cancel()
        except Exception as e:
            logger.warning(f"Embedded WSS reconnecting in 5s: {e}")
            await asyncio.sleep(5)
