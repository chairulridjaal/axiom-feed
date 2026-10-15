"""Deduplicate bounded work independently of every request waiter's cancellation.

The service uses asyncio-native transports and request cancellation. The producer
is explicitly owned by this registry until completion or its finite deadline.
"""

from __future__ import annotations

import asyncio  # Backend-native shielding with bounded registry ownership.
import math
from collections.abc import Awaitable, Callable
from typing import Generic, TypeVar

T = TypeVar("T")


class Singleflight(Generic[T]):
    def __init__(self, timeout_seconds: float = 30.0) -> None:
        if not math.isfinite(timeout_seconds) or timeout_seconds < 0:
            msg = "singleflight deadline must be finite and nonnegative"
            raise ValueError(msg)
        self._timeout_seconds = timeout_seconds
        self._in_flight: dict[str, asyncio.Task[T]] = {}

    async def do(self, key: str, coro_fn: Callable[[], Awaitable[T]]) -> T:
        """Run once per key; cancelling any caller leaves shared work intact."""
        task = self._in_flight.get(key)
        if task is None:
            # No await between lookup and registration: atomic on the event loop.
            async def produce() -> T:
                try:
                    async with asyncio.timeout(self._timeout_seconds):
                        return await coro_fn()
                finally:
                    self._in_flight.pop(key, None)

            task = asyncio.create_task(produce(), name=f"singleflight:{key}")
            self._in_flight[key] = task
            task.add_done_callback(self._observe_completion)
        return await asyncio.shield(task)

    @staticmethod
    def _observe_completion(task: asyncio.Task[T]) -> None:
        # An abandoned producer still has an owner that retrieves its exception.
        if not task.cancelled():
            task.exception()

    def in_flight_count(self) -> int:
        return len(self._in_flight)
