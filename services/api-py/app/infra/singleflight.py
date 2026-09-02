"""Singleflight — in-flight request deduplication.

Suppresses duplicate concurrent async operations for the same key.
When multiple coroutines call singleflight.do(key, coro_fn), only the first
coroutine executes coro_fn, while subsequent callers await the same result.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine
from typing import Any, TypeVar

T = TypeVar("T")


class Singleflight:
    def __init__(self) -> None:
        self._in_flight: dict[str, asyncio.Future[Any]] = {}
        self._lock = asyncio.Lock()

    async def do(self, key: str, coro_fn: Callable[[], Coroutine[Any, Any, T]]) -> T:
        """Execute coro_fn once for key while in-flight; concurrent callers share result."""
        fut: asyncio.Future[Any] | None = None
        is_leader = False

        async with self._lock:
            if key in self._in_flight:
                fut = self._in_flight[key]
            else:
                loop = asyncio.get_running_loop()
                fut = loop.create_future()
                self._in_flight[key] = fut
                is_leader = True

        if not is_leader:
            assert fut is not None
            return await fut

        try:
            result = await coro_fn()
            if not fut.cancelled():
                fut.set_result(result)
            return result
        except BaseException as e:
            if not fut.cancelled():
                fut.set_exception(e)
            raise
        finally:
            async with self._lock:
                self._in_flight.pop(key, None)

    def in_flight_count(self) -> int:
        return len(self._in_flight)
