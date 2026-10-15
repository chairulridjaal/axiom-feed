"""Hermetic tests: no credential files, real HTTP, shared ticks or live ingestion."""

import os
import tempfile
from pathlib import Path

import dotenv
import httpx
import pytest

_sandbox = tempfile.TemporaryDirectory(prefix="axiom-feed-pytest-")
for _key in ("STOCKBIT_BEARER_TOKEN", "STOCKBIT_REFRESH_TOKEN", "REDIS_URL", "API_KEY"):
    os.environ[_key] = ""
os.environ["TICKS_DB_PATH"] = str(Path(_sandbox.name) / "ticks.db")
os.environ["INGEST_MODE"] = "test"
# app.main is imported during collection. Disable dotenv before that import.
dotenv.load_dotenv = lambda *args, **kwargs: False


@pytest.fixture(scope="session", autouse=True)
def offline_runtime():
    from app.infra.tick_store import TickStore
    from app.providers.stockbit import provider

    patch = pytest.MonkeyPatch()
    stores = []
    attempts = []

    def store(*args, **kwargs):
        result = TickStore(*args, **kwargs)
        stores.append(result)
        return result

    def deny_http(*args, **kwargs):
        attempts.append(True)
        raise AssertionError("Real HTTP is disabled in the feed test suite")

    async def deny_async_http(*args, **kwargs):
        deny_http()

    patch.setattr(provider, "TickStore", store)
    patch.setattr(httpx.HTTPTransport, "handle_request", deny_http)
    patch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", deny_async_http)
    yield
    for item in stores:
        item.close()
    patch.undo()
    _sandbox.cleanup()
    assert not attempts, "A test attempted real HTTP; install an explicit offline fixture"
