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
    def __init__(self, rps: float = 10.0):
        self.rps = rps
        self._tokens = rps
        self._updated = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            now = time.monotonic()
            elapsed = now - self._updated
            self._updated = now
            self._tokens = min(self.rps, self._tokens + elapsed * self.rps)
            if self._tokens < 1:
                wait = (1 - self._tokens) / self.rps
                self._tokens = 0
            else:
                wait = 0.0
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
        self.concurrency = concurrency
        self.limiter = RateLimiter(rps=rps)
        self._sem: asyncio.Semaphore | None = None
        self._client: httpx.AsyncClient | None = None

    def semaphore(self) -> asyncio.Semaphore:
        try:
            loop = asyncio.get_running_loop()
            if self._sem is None or getattr(self._sem, "_loop", None) != loop:
                self._sem = asyncio.Semaphore(self.concurrency)
        except Exception:
            if self._sem is None:
                self._sem = asyncio.Semaphore(self.concurrency)
        return self._sem

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
        if self._client is not None:
            try:
                loop = asyncio.get_running_loop()
                transport = getattr(self._client, "_transport", None)
                transport_loop = getattr(transport, "_loop", None)
                if self._client.is_closed or (
                    transport_loop is not None and transport_loop != loop
                ):
                    self._client = None
            except Exception:
                pass
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
        async with self.semaphore():
            resp = await self.client().get(url, params=params)
            if resp.status_code == 401:
                from app.providers.stockbit.auth import get_auth

                auth = get_auth()
                if auth and auth.refresh_token:
                    try:
                        logger.info(
                            "401 received in get_json — attempting silent refresh via refresh_token"
                        )
                        await auth.refresh_tokens_via_stockbit()
                        resp = await self.client().get(url, params=params)
                    except Exception as e:
                        logger.warning(f"On-demand refresh failed after 401: {e}")
            if resp.status_code == 429:
                ra = resp.headers.get("Retry-After")
                if ra:
                    try:
                        await asyncio.sleep(float(ra))
                    except Exception:
                        await asyncio.sleep(1)
            resp.raise_for_status()
            return orjson.loads(resp.content)

    async def stream_json_array(
        self,
        url: str,
        params: dict[str, Any] | None = None,
        array_key: str = "data",
    ) -> AsyncIterator[dict[str, Any]]:
        await self.limiter.acquire()
        async with self.semaphore():
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
                in_array = False
                in_string = False
                escape = False
                brace_depth = 0
                obj_start = -1
                yielded_any = False
                i = 0
                consumed_index = 0

                async for chunk in resp.aiter_bytes():
                    buf.extend(chunk)
                    while i < len(buf):
                        c = buf[i]
                        if in_string:
                            if escape:
                                escape = False
                            elif c == 92:
                                escape = True
                            elif c == 34:
                                in_string = False
                            i += 1
                            continue

                        if c == 34:
                            in_string = True
                            i += 1
                            continue

                        if not in_array:
                            if c == 91:
                                in_array = True
                                del buf[: i + 1]
                                i = 0
                                consumed_index = 0
                                obj_start = -1
                                continue
                            i += 1
                            continue

                        if c == 123:
                            if brace_depth == 0:
                                obj_start = i
                            brace_depth += 1
                        elif c == 125:
                            brace_depth -= 1
                            if brace_depth == 0 and obj_start != -1:
                                raw_obj = buf[obj_start : i + 1]
                                try:
                                    item = orjson.loads(raw_obj)
                                    if isinstance(item, dict):
                                        yield item
                                        yielded_any = True
                                except Exception:
                                    pass
                                consumed_index = i + 1
                                obj_start = -1
                                if consumed_index > 65536:
                                    del buf[:consumed_index]
                                    i -= consumed_index
                                    consumed_index = 0
                        elif c == 93 and brace_depth == 0:
                            in_array = False
                            del buf[: i + 1]
                            i = 0
                            consumed_index = 0
                            obj_start = -1
                            continue

                        i += 1

                if consumed_index > 0 and consumed_index < len(buf):
                    del buf[:consumed_index]

                if not yielded_any and buf:
                    try:
                        data = orjson.loads(buf)
                        if isinstance(data, dict):
                            items = data
                            if array_key in data:
                                items = data[array_key]
                                if isinstance(items, dict):
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
                    except Exception:
                        pass


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
