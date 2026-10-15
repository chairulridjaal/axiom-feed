"""A bounded authenticated JSON read for complete taxonomy snapshots."""

import orjson
from pydantic import JsonValue, TypeAdapter, ValidationError

from app.providers.stockbit.transport import HttpxTransport
from app.reference.taxonomy import CatalogueError
from app.reference.wire import WireJSON

_JSON = TypeAdapter(JsonValue)


async def bounded_taxonomy_json(transport: HttpxTransport, url: str, max_bytes: int) -> WireJSON:
    await transport.limiter.acquire()
    async with transport.semaphore():
        async with transport.client().stream("GET", url) as response:
            response.raise_for_status()
            body = bytearray()
            async for chunk in response.aiter_bytes(chunk_size=16_384):
                if len(body) + len(chunk) > max_bytes:
                    raise CatalogueError("Taxonomy response byte budget exceeded")
                body.extend(chunk)
    try:
        return WireJSON(_JSON.validate_python(orjson.loads(body)), len(body))
    except (orjson.JSONDecodeError, ValidationError) as exc:
        raise CatalogueError("Invalid taxonomy JSON") from exc
