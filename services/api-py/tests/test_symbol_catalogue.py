from collections import Counter
from hashlib import sha256

import anyio
import httpx
import pytest
from anyio.lowlevel import checkpoint
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import JsonValue, TypeAdapter

from app.core.security import verify_api_key


def company(symbol: str, **changes: JsonValue) -> dict[str, JsonValue]:
    return {
        "symbol": symbol,
        "type_company": "Saham",
        "country": "ID",
        "company_status": "STATUS_ACTIVE",
        **changes,
    }


class TaxonomyProvider:
    def __init__(self):
        self.calls = Counter()
        self.failure = False
        self.root = {
            "data": [
                {"id": value, "name": "Reviewed equity sector " + str(value)}
                for value in [1, 2, 3, 4, 5, 6, 7, 8, 9, 50, 51]
            ]
        }
        self.children = {"data": [{"id": 15, "name": "Banks"}]}
        self.companies: dict[str, JsonValue] = {
            "data": [company("BBRI"), company("BBCA"), company("BBCA")]
        }

    async def sector_list(self, *, max_bytes: int) -> JsonValue:
        self.calls["root"] += 1
        await checkpoint()
        if self.failure:
            raise httpx.ReadError("synthetic outage")
        return TypeAdapter(JsonValue).validate_python(self.root)

    async def subsectors(self, sid: str, *, max_bytes: int) -> JsonValue:
        self.calls["children"] += 1
        return TypeAdapter(JsonValue).validate_python(self.children)

    async def sector_companies(self, sid: str, sub_id: str, *, max_bytes: int) -> JsonValue:
        self.calls["companies"] += 1
        return TypeAdapter(JsonValue).validate_python(self.companies)


@pytest.mark.asyncio
async def test_catalogue_is_atomic_sorted_taxonomy_snapshot():
    from app.reference.catalogue import SymbolCatalogue

    provider = TaxonomyProvider()
    service = SymbolCatalogue(provider)
    result = await service.get()
    assert result.symbols == ("BBCA", "BBRI")
    assert result.count == 2
    assert result.scope == "provider_equity_sector_taxonomy"
    assert result.complete is True
    assert result.checksum == sha256(b"BBCA\nBBRI").hexdigest()
    assert await service.get() is result
    assert provider.calls == {"root": 1, "children": 11, "companies": 11}


@pytest.mark.asyncio
async def test_concurrent_catalogue_requests_share_one_complete_crawl():
    from app.reference.catalogue import SymbolCatalogue

    provider = TaxonomyProvider()
    service = SymbolCatalogue(provider)
    results = []

    async def read():
        results.append(await service.get())

    async with anyio.create_task_group() as group:
        for _ in range(10):
            group.start_soon(read)
    assert len(results) == 10
    assert all(item is results[0] for item in results)
    assert provider.calls["root"] == 1


@pytest.mark.asyncio
async def test_failed_refresh_never_replaces_last_good_snapshot():
    from app.reference.catalogue import CatalogueLimits, SymbolCatalogue

    now = [0.0]
    provider = TaxonomyProvider()
    service = SymbolCatalogue(provider, CatalogueLimits(ttl_seconds=1), clock=lambda: now[0])
    good = await service.get()
    now[0] = 2.0
    provider.failure = True
    with pytest.raises(httpx.ReadError):
        await service.get()
    assert service.last_success is good
    provider.failure = False
    provider.companies = {"data": [company("BMRI")]}
    fresh = await service.get()
    assert fresh.symbols == ("BMRI",)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "part,payload",
    [
        ("root", {"data": []}),
        ("root", {"error": "unavailable"}),
        ("root", {"data": [{"name": "missing id"}]}),
        ("root", {"data": [{"id": "../secret"}]}),
        ("children", {"data": [{"id": 15}], "pagination": {"total": 2}}),
        ("companies", {"data": [{"symbol": "BBCA"}], "next_page": 2}),
        ("companies", {"data": [{"symbol": "BBCA"}], "total": 2}),
        ("companies", {"data": [{"symbol": "BBCA;DROP"}]}),
        ("companies", {"data": [{"symbol": "BBCA"}, {}]}),
    ],
)
async def test_incomplete_or_malformed_taxonomy_fails_as_whole(part, payload):
    from app.reference.catalogue import SymbolCatalogue
    from app.reference.taxonomy import CatalogueError

    provider = TaxonomyProvider()
    setattr(provider, part, payload)
    service = SymbolCatalogue(provider)
    with pytest.raises(CatalogueError):
        await service.get()
    assert service.last_success is None


@pytest.mark.asyncio
@pytest.mark.parametrize("limit,value", [("max_calls", 2), ("max_rows", 3), ("max_bytes", 10)])
async def test_catalogue_budget_exhaustion_cannot_publish_partial(limit, value):
    from app.reference.catalogue import CatalogueLimits, SymbolCatalogue
    from app.reference.taxonomy import CatalogueError

    service = SymbolCatalogue(TaxonomyProvider(), CatalogueLimits(**{limit: value}))
    with pytest.raises(CatalogueError):
        await service.get()
    assert service.last_success is None


def test_reference_route_and_sector_outage_are_explicit_503(monkeypatch):
    from app.api.v1 import reference, sectors
    from app.reference.catalogue import SymbolCatalogue

    provider = TaxonomyProvider()
    provider.failure = True
    monkeypatch.setattr(reference, "catalogue", SymbolCatalogue(provider))
    monkeypatch.setattr(sectors, "get_provider", lambda: provider)
    from app.infra.upstream_cache import upstream_cache

    upstream_cache.clear()
    app = FastAPI()
    app.dependency_overrides[verify_api_key] = lambda: None
    app.include_router(reference.router)
    app.include_router(sectors.router)
    with TestClient(app) as client:
        assert client.get("/v1/reference/symbols").status_code == 503
        assert client.get("/v1/sectors").status_code == 503


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "metadata",
    [
        {"next_cursor": "remaining"},
        {"pagination": {"total": 1, "next_cursor": "remaining"}},
        {"links": {"next": "/page/2"}},
        {"offset": 0, "limit": 1},
        {"pagination": {"total": 1, "unknown_marker": True}},
    ],
)
async def test_unrecognized_or_truncated_pagination_never_publishes(metadata):
    from app.reference.catalogue import SymbolCatalogue
    from app.reference.taxonomy import CatalogueError

    provider = TaxonomyProvider()
    provider.companies = {"data": [company("BBCA")], **metadata}
    service = SymbolCatalogue(provider)
    with pytest.raises(CatalogueError):
        await service.get()
    assert service.last_success is None


@pytest.mark.asyncio
async def test_aggregate_decompressed_wire_bytes_are_enforced_before_snapshot():
    import orjson

    from app.providers.stockbit.provider import StockbitProvider
    from app.providers.stockbit.transport import HttpxTransport
    from app.reference.catalogue import CatalogueLimits, SymbolCatalogue
    from app.reference.taxonomy import CatalogueError

    bodies = [
        orjson.dumps(TaxonomyProvider().root),
        b'{"data":[{"id":15}]}',
        orjson.dumps({"data": [company("BBCA")]}),
    ]
    calls = []

    def reply(request):
        body = bodies[len(calls)] + b" " * 80
        calls.append(len(body))
        return httpx.Response(200, content=body)

    provider = StockbitProvider.__new__(StockbitProvider)
    provider.transport = HttpxTransport()
    async with httpx.AsyncClient(transport=httpx.MockTransport(reply)) as client:
        provider.transport._client = client
        service = SymbolCatalogue(
            provider,
            CatalogueLimits(max_bytes=sum(map(len, bodies)) + 160, max_response_bytes=1_000_000),
        )
        with pytest.raises(CatalogueError, match="byte budget"):
            await service.get()
        assert len(calls) == 3
        assert service.last_success is None


@pytest.mark.parametrize(
    "payload",
    [{"error": "expired"}, {"data": None}, {"data": [{}]}, {"data": [], "success": False}],
)
@pytest.mark.parametrize(
    "path", ["/v1/sectors", "/v1/sectors/1/subsectors", "/v1/sectors/1/subsectors/15/companies"]
)
def test_malformed_sector_envelopes_are_503_and_not_cached(monkeypatch, payload, path):
    from app.api.v1 import sectors
    from app.infra.upstream_cache import upstream_cache

    provider = TaxonomyProvider()
    provider.root = provider.children = provider.companies = payload
    monkeypatch.setattr(sectors, "get_provider", lambda: provider)
    upstream_cache.clear()
    app = FastAPI()
    app.dependency_overrides[verify_api_key] = lambda: None
    app.include_router(sectors.router)
    with TestClient(app) as client:
        assert client.get(path).status_code == 503
        provider.root = {"data": [{"id": 1, "name": "Finance"}]}
        provider.children = {"data": [{"id": 15}]}
        provider.companies = {"data": [company("BBCA")]}
        assert client.get(path).status_code == 200


@pytest.mark.asyncio
async def test_equity_positive_membership_excludes_other_assets_countries_and_status():
    from app.reference.catalogue import SymbolCatalogue

    provider = TaxonomyProvider()
    provider.companies = {
        "data": [
            company("BBCA"),
            company("USD", type_company="Currencies", country=""),
            company("BTC", type_company="Crypto", country=""),
            company("AAPL", country="US"),
            company("OLD", company_status="STATUS_DELISTED"),
        ]
    }
    assert (await SymbolCatalogue(provider).get()).symbols == ("BBCA",)


@pytest.mark.asyncio
async def test_missing_equity_classification_never_becomes_positive():
    from app.reference.catalogue import SymbolCatalogue
    from app.reference.taxonomy import CatalogueError

    provider = TaxonomyProvider()
    provider.companies = {"data": [{"symbol": "BBCA", "type_company": "Saham"}]}
    with pytest.raises(CatalogueError):
        await SymbolCatalogue(provider).get()


@pytest.mark.asyncio
async def test_reviewed_equity_roots_are_all_required():
    from app.reference.catalogue import SymbolCatalogue
    from app.reference.taxonomy import CatalogueError

    provider = TaxonomyProvider()
    provider.root["data"].pop()
    with pytest.raises(CatalogueError):
        await SymbolCatalogue(provider).get()


@pytest.mark.asyncio
async def test_unselected_asset_roots_are_not_crawled_or_equity_claimed():
    from app.reference.catalogue import SymbolCatalogue

    provider = TaxonomyProvider()
    provider.root["data"].append({"id": 75, "name": "Crypto"})
    result = await SymbolCatalogue(provider).get()
    assert result.scope == "provider_equity_sector_taxonomy"
    assert provider.calls["children"] == 11


@pytest.mark.asyncio
async def test_empty_selected_subsector_branch_is_honest_unavailable():
    from app.reference.catalogue import SymbolCatalogue
    from app.reference.taxonomy import CatalogueError

    provider = TaxonomyProvider()
    provider.children = {"data": []}
    with pytest.raises(CatalogueError):
        await SymbolCatalogue(provider).get()
