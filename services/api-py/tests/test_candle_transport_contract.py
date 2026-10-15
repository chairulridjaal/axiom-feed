from asyncio import Semaphore
from types import SimpleNamespace

import anyio
import httpx
import pytest

from app.providers.stockbit.transport import HttpxTransport


class Chunks(httpx.AsyncByteStream):
    def __init__(self, chunks):
        self.chunks = chunks
        self.closed = False

    async def __aiter__(self):
        for chunk in self.chunks:
            yield chunk

    async def aclose(self):
        self.closed = True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "chunks,limit,object_limit",
    [
        ([b'{"data":[{"close":1}]}'], 5, 100),
        ([b'{"data":[{"close":"', b"x" * 70, b'"}]}'], 200, 64),
        ([b'{"data":[{"close":1}', b',{"close":'], 200, 100),
        ([b'{"data":[{"close":1}]}TRAILING'], 200, 100),
        ([b'{"data":[1,2]}'], 200, 100),
        ([b'{"meta":[{"close":1}],"data":[]}'], 200, 100),
    ],
)
async def test_strict_candle_transport_rejects_excess_or_incomplete_wire(
    chunks, limit, object_limit, monkeypatch
):
    # Given: an offline streamed response through the real HTTP adapter.
    body = Chunks(chunks)

    async def acquire():
        return None

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, stream=body))
    ) as client:
        transport = HttpxTransport.__new__(HttpxTransport)
        transport.client = lambda: client
        monkeypatch.setattr(transport, "limiter", SimpleNamespace(acquire=acquire), raising=False)
        transport.semaphore = lambda: Semaphore(1)
        # When: consuming the strict candle transport contract.
        with pytest.raises((ValueError, RuntimeError)):
            async for _ in transport.stream_json_array(
                "https://fixture.test/candles", max_bytes=limit, max_object_bytes=object_limit
            ):
                pass
    # Then: it fails explicitly and closes the upstream response.
    assert body.closed is True


@pytest.mark.asyncio
async def test_strict_candle_transport_accepts_exact_budget(monkeypatch):
    wire = b'{"data":[{"close":1}]}'
    body = Chunks([wire])

    async def acquire():
        return None

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, stream=body))
    ) as client:
        transport = HttpxTransport.__new__(HttpxTransport)
        transport.client = lambda: client
        monkeypatch.setattr(transport, "limiter", SimpleNamespace(acquire=acquire), raising=False)
        transport.semaphore = lambda: Semaphore(1)
        result = [
            row
            async for row in transport.stream_json_array(
                "https://fixture.test/candles",
                max_bytes=len(wire),
                max_object_bytes=len(b'{"close":1}'),
            )
        ]
    assert result == [{"close": 1}]
    assert body.closed is True


@pytest.mark.asyncio
async def test_cancelled_strict_transport_closes_upstream(monkeypatch):
    started = anyio.Event()

    class Blocked(Chunks):
        async def __aiter__(self):
            started.set()
            yield b'{"data":['
            await anyio.sleep_forever()

    body = Blocked([])

    async def acquire():
        return None

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, stream=body))
    ) as client:
        transport = HttpxTransport.__new__(HttpxTransport)
        transport.client = lambda: client
        monkeypatch.setattr(transport, "limiter", SimpleNamespace(acquire=acquire), raising=False)
        transport.semaphore = lambda: Semaphore(1)

        async def consume():
            async for _ in transport.stream_json_array(
                "https://fixture.test/candles", max_bytes=1000, max_object_bytes=100
            ):
                pass

        async with anyio.create_task_group() as group:
            group.start_soon(consume)
            await started.wait()
            group.cancel_scope.cancel()
    assert body.closed is True
