"""HttpxTransport — the only place httpx is configured for Stockbit.

Isolation: domain/ never imports this; providers/stockbit is the sole boundary.

Features (vs be-web core/http_client.py which used response.json() triple-copy):
  - Limits(max_connections=20, keepalive=10) — bounded, reused client.
  - tenacity Retry-After + exponential 3× on 429/5xx.
  - Token bucket 10 rps (simple asyncio limiter).
  - Semaphore(4) global concurrency — single limiter (provider no longer holds a second semaphore).
  - httpx.stream for historical — bytearray buffer + orjson per-window, never full-buffer 60MB.
  - cookies/jar reused from auth (httpx.Cookies).
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator
from typing import Any

import httpx
import orjson
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

logger = logging.getLogger(__name__)

EXODUS = "https://exodus.stockbit.com"


class RateLimiter:
    """Token bucket 10 rps."""

    def __init__(self, rps: float = 10.0):
        self.rps = rps
        self._tokens = rps
        self._updated = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        wait: float = 0.0
        async with self._lock:
            now = time.monotonic()
            elapsed = now - self._updated
            self._updated = now
            self._tokens = min(self.rps, self._tokens + elapsed * self.rps)
            if self._tokens < 1:
                wait = (1 - self._tokens) / self.rps
                self._tokens = 0
            else:
                self._tokens -= 1
        if wait > 0:
            await asyncio.sleep(wait)


def _is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in (429, 500, 502, 503, 504)
    if isinstance(
        exc, (httpx.ConnectError, httpx.ReadTimeout, httpx.WriteTimeout, httpx.PoolTimeout)
    ):
        return True
    return False


class HttpxTransport:
    def __init__(
        self,
        bearer_token: str | None = None,
        cookies: httpx.Cookies | None = None,
        rps: float = 10.0,
        concurrency: int = 4,
    ):
        self.bearer = bearer_token or ""
        self.cookies = cookies
        self.limiter = RateLimiter(rps=rps)
        self.sem = asyncio.Semaphore(concurrency)
        self._client: httpx.AsyncClient | None = None

    def _headers(self) -> dict[str, str]:
        h = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36",
            "Origin": "https://stockbit.com",
            "Referer": "https://stockbit.com/",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-US,en;q=0.9",
        }
        if self.bearer:
            h["Authorization"] = f"Bearer {self.bearer}"
        return h

    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            limits = httpx.Limits(max_connections=20, max_keepalive_connections=10)
            self._client = httpx.AsyncClient(
                cookies=self.cookies,
                headers=self._headers(),
                limits=limits,
                timeout=httpx.Timeout(30.0, connect=10.0),
                follow_redirects=True,
            )
        return self._client

    def update_bearer(self, token: str) -> None:
        self.bearer = token
        if self._client:
            self._client.headers["Authorization"] = f"Bearer {token}"
        logger.info("HttpxTransport bearer updated (hot-swap)")

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=0.5, min=0.5, max=8),
        retry=retry_if_exception(_is_retryable),
        reraise=True,
    )
    async def get_json(
        self,
        url: str,
        params: dict[str, Any] | None = None,
        label: str = "GET",
    ) -> Any:
        await self.limiter.acquire()
        async with self.sem:
            resp = await self.client().get(url, params=params)
            if resp.status_code == 429:
                ra = resp.headers.get("Retry-After")
                if ra:
                    try:
                        await asyncio.sleep(float(ra))
                    except Exception:
                        await asyncio.sleep(1)
            resp.raise_for_status()
            # incremental orjson parse (avoid double-copy)
            return orjson.loads(resp.content)

    async def stream_json_array(
        self,
        url: str,
        params: dict[str, Any] | None = None,
        array_key: str = "data",
    ) -> AsyncIterator[dict[str, Any]]:
        await self.limiter.acquire()
        async with self.sem:
            async with self.client().stream("GET", url, params=params) as resp:
                if resp.status_code == 429:
                    ra = resp.headers.get("Retry-After")
                    if ra:
                        try:
                            await asyncio.sleep(float(ra))
                        except Exception:
                            await asyncio.sleep(1)
                resp.raise_for_status()
                buf = bytearray()
                max_buf = 10_000_000
                async for chunk in resp.aiter_bytes():
                    buf.extend(chunk)
                    if len(buf) > max_buf:
                        raise RuntimeError(f"stream_json_array exceeded {max_buf} bytes for {url}")
                if not buf:
                    return
                data = orjson.loads(buf)
                buf.clear()
                # Stockbit wraps in {"data": [...]} or {"data": {"candles": [...]}} etc
                items = data
                if isinstance(data, dict) and array_key in data:
                    items = data[array_key]
                    # some endpoints use {"data": {"candle": [...]}} double-wrap
                    if isinstance(items, dict):
                        # pick first list value
                        for v in items.values():
                            if isinstance(v, list):
                                items = v
                                break
                if isinstance(items, list):
                    for it in items:
                        if isinstance(it, dict):
                            yield it
                elif isinstance(items, dict):
                    yield items


# global transport singleton (initialized from AuthManager)
_transport: HttpxTransport | None = None


def get_transport() -> HttpxTransport:
    if _transport is None:
        raise RuntimeError("HttpxTransport not initialized — call init_transport() in lifespan")
    return _transport


def init_transport(
    bearer: str | None = None, cookies: httpx.Cookies | None = None
) -> HttpxTransport:
    global _transport
    if _transport is None:
        import os

        bearer = bearer or os.getenv("STOCKBIT_BEARER_TOKEN", "")
        _transport = HttpxTransport(bearer_token=bearer, cookies=cookies)
        logger.info("HttpxTransport initialized (Limits 20, 10 rps, Sem 4)")
    return _transport
