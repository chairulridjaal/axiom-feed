import anyio
import pytest
from pydantic import JsonValue
from test_symbol_catalogue import TaxonomyProvider


@pytest.mark.asyncio
async def test_canceled_first_waiter_does_not_abort_complete_snapshot():
    from app.reference.catalogue import SymbolCatalogue

    entered = anyio.Event()
    release = anyio.Event()
    canceled = anyio.Event()

    class PausedProvider(TaxonomyProvider):
        async def sector_list(self, *, max_bytes: int) -> JsonValue:
            entered.set()
            await release.wait()
            return await super().sector_list(max_bytes=max_bytes)

    provider = PausedProvider()
    service = SymbolCatalogue(provider)

    async def first():
        with anyio.CancelScope() as scope:

            async def cancel():
                await entered.wait()
                scope.cancel()

            async with anyio.create_task_group() as group:
                group.start_soon(cancel)
                await service.get()
        canceled.set()

    async with anyio.create_task_group() as group:
        group.start_soon(first)
        await canceled.wait()
        release.set()
        snapshot = await service.get()
    assert snapshot.symbols == ("BBCA", "BBRI")
    assert service.last_success is snapshot
    assert provider.calls["root"] == 1


@pytest.mark.asyncio
async def test_catalogue_deadline_cancels_producer_without_publishing():
    from app.reference.catalogue import CatalogueLimits, SymbolCatalogue

    closed = []

    class StuckProvider(TaxonomyProvider):
        async def sector_list(self, *, max_bytes: int) -> JsonValue:
            try:
                await anyio.sleep_forever()
            finally:
                closed.append(True)

    service = SymbolCatalogue(StuckProvider(), CatalogueLimits(timeout_seconds=0.01))
    with pytest.raises(TimeoutError):
        await service.get()
    assert closed == [True]
    assert service.last_success is None


@pytest.mark.asyncio
async def test_valid_empty_company_page_does_not_hide_other_positive_branches():
    from app.reference.catalogue import SymbolCatalogue

    class EmptyBranchProvider(TaxonomyProvider):
        async def sector_companies(self, sid: str, sub_id: str, *, max_bytes: int) -> JsonValue:
            if sid == "1":
                return {
                    "data": [],
                    "pagination": {
                        "next_page": 0,
                        "prev_page": 0,
                        "current_page": 1,
                        "total_page": 0,
                        "data_per_page": 10000,
                        "total_data_in_page": 0,
                        "total_data": 0,
                    },
                }
            return await super().sector_companies(sid, sub_id, max_bytes=max_bytes)

    snapshot = await SymbolCatalogue(EmptyBranchProvider()).get()
    assert snapshot.complete is True
    assert snapshot.symbols == ("BBCA", "BBRI")
