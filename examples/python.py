"""Minimal Python client — httpx + websockets, no SDK needed."""
import asyncio
import json

import httpx
import websockets

BASE = "http://localhost:8000"
API_KEY = ""  # set if API_KEY is configured server-side

# REST — candles stream as NDJSON (one JSON per line)
with httpx.Client(timeout=30) as c:
    # daily sliced, streamed
    with c.stream("GET", f"{BASE}/v1/candles/BBCA", params={"from": "2026-08-01", "to": "2026-08-26", "resolution": "daily"}) as r:
        r.raise_for_status()
        for line in r.iter_lines():
            if line:
                print(json.loads(line))
                break
    print("health:", c.get(f"{BASE}/v1/health", headers={"X-API-Key": API_KEY} if API_KEY else {}).json())
    print("quote:", c.get(f"{BASE}/v1/quotes/BBCA", headers={"X-API-Key": API_KEY} if API_KEY else {}).json())
    print("book:", c.get(f"{BASE}/v1/books/BBCA", headers={"X-API-Key": API_KEY} if API_KEY else {}).json())


async def ws_demo():
    uri = f"ws://localhost:8000/v1/stream?token={API_KEY}" if API_KEY else "ws://localhost:8000/v1/stream"
    async with websockets.connect(uri) as ws:
        # subscribe explicit symbols — '*' only for trades, rejected for quotes/books
        await ws.send(json.dumps({"action": "subscribe", "symbols": ["BBCA"], "kinds": ["trades", "quotes", "books"]}))
        print("subscribed:", await ws.recv())
        await ws.send(json.dumps({"action": "ping"}))
        print("pong:", await ws.recv())
        # error case: '*' for quotes/books should be rejected with actionable message
        await ws.send(json.dumps({"action": "subscribe", "symbols": ["*"], "kinds": ["quotes"]}))
        print("wildcard rejection:", await ws.recv())


if __name__ == "__main__":
    asyncio.run(ws_demo())
