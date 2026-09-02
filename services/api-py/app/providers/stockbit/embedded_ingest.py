"""Embedded live feed runner using websockets in Python (INGEST_MODE=embedded or dev)."""

import asyncio
import logging
import os
import zlib

logger = logging.getLogger(__name__)


def decompress(raw: bytes) -> bytes:
    for candidate in (raw, raw + b"\x00\x00\xff\xff"):
        try:
            return zlib.decompress(candidate, -15)
        except Exception:
            pass
    return raw


async def run_embedded_ingest(provider, hub):
    """Connect directly to Stockbit WSS in Python, decode, and feed into live provider + hub."""
    from typing import Any

    import websockets

    from app.providers.stockbit.auth import get_auth
    from app.providers.stockbit.generated import datafeed_pb2 as pb_module
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
    ws_url = os.getenv("STOCKBIT_WS_URL", "wss://wss-jkt.trading.stockbit.com/ws")
    headers = {
        "Origin": "https://stockbit.com",
        "Authorization": f"Bearer {creds.bearer_token}",
        "User-Agent": "Mozilla/5.0",
        "Accept-Encoding": "gzip, deflate, br",
    }

    logger.info(f"Embedded WSS connecting to {ws_url} for user {creds.user_id}...")
    while True:
        try:
            async with websockets.connect(ws_url, additional_headers=headers) as ws:
                logger.info("Embedded WSS connected to Stockbit live feed")

                # Send full subscription
                sub = pb.WebsocketRequest()
                sub.user_id = creds.user_id
                sub.key = creds.ws_key
                sub.channel.running_trade_batch.extend(["*"])
                sub.channel.watchlist.extend(["*"])

                # explicit symbols
                seed = [s.strip().upper() for s in os.getenv("SUBSCRIBE_SYMBOLS", "BBCA,TLKM,IHSG,BBRI,BMRI").split(",") if s.strip()]
                sub.channel.liveprice.extend(seed)
                sub.channel.order_book.extend(seed)

                await ws.send(sub.SerializeToString())
                logger.info(f"Embedded WSS sent full subscription (trades=* seed={seed})")

                # Ping task
                async def ping_loop():
                    while True:
                        await asyncio.sleep(25)
                        p = pb.WebsocketRequest()
                        p.ping.timestamp.GetCurrentTime()
                        await ws.send(p.SerializeToString())

                p_task = asyncio.create_task(ping_loop())
                try:
                    async for raw_msg in ws:
                        if isinstance(raw_msg, bytes):
                            data = decompress(raw_msg)
                            wrapper = pb.WebsocketWrapMessageChannel()
                            try:
                                wrapper.ParseFromString(data)
                                which = wrapper.WhichOneof("message_channel")
                                if which == "running_trade_batch":
                                    for t in wrapper.running_trade_batch.trades:
                                        from app.providers.stockbit.mapping import (
                                            map_running_trade_to_domain,
                                        )
                                        trade = map_running_trade_to_domain(t)
                                        provider.live_feed().ingest_trade(trade)
                                        await hub.publish({"kind": "trade", "symbol": trade.symbol, "payload": {
                                            "stock": trade.symbol, "price": float(trade.price), "volume": trade.volume,
                                            "side": str(trade.side.value if hasattr(trade.side, 'value') else trade.side),
                                            "trade_number": trade.seq
                                        }})
                                elif which == "running_trade":
                                    from app.providers.stockbit.mapping import (
                                        map_running_trade_to_domain,
                                    )
                                    trade = map_running_trade_to_domain(wrapper.running_trade)
                                    provider.live_feed().ingest_trade(trade)
                                    await hub.publish({"kind": "trade", "symbol": trade.symbol, "payload": {
                                        "stock": trade.symbol, "price": float(trade.price), "volume": trade.volume,
                                        "side": str(trade.side.value if hasattr(trade.side, 'value') else trade.side),
                                        "trade_number": trade.seq
                                    }})
                                elif which == "liveprice":
                                    from app.providers.stockbit.mapping import (
                                        map_liveprice_to_quote,
                                    )
                                    q = map_liveprice_to_quote(wrapper.liveprice)
                                    provider.live_feed().ingest_quote(q)
                                    await hub.publish({"kind": "quote", "symbol": q.symbol, "payload": {
                                        "stock": q.symbol, "price": float(q.last), "open": float(q.open) if q.open else None,
                                        "high": float(q.high) if q.high else None, "low": float(q.low) if q.low else None
                                    }})
                                elif which == "orderbook_body":
                                    from app.providers.stockbit.mapping import (
                                        map_orderbook_body_to_book,
                                    )
                                    ob = wrapper.orderbook_body
                                    book = map_orderbook_body_to_book(ob.stock_symbol, ob.bid, ob.offer)
                                    provider.live_feed().ingest_book(book)
                            except Exception:
                                pass
                finally:
                    p_task.cancel()
        except Exception as e:
            logger.warning(f"Embedded WSS reconnecting in 5s: {e}")
            await asyncio.sleep(5)
