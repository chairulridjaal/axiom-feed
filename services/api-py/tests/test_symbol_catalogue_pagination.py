import pytest
from pydantic import JsonValue, TypeAdapter
from test_symbol_catalogue import TaxonomyProvider, company


@pytest.mark.asyncio
async def test_actual_provider_complete_pagination_envelope_is_accepted():
    from app.reference.catalogue import SymbolCatalogue

    provider = TaxonomyProvider()
    provider.companies = {
        "data": [company("BBCA")],
        "message": "Found 1 companies in subsector",
        "pagination": {
            "next_page": 0,
            "prev_page": 0,
            "current_page": 1,
            "total_page": 1,
            "data_per_page": 10000,
            "total_data_in_page": 1,
            "total_data": 1,
        },
    }
    assert (await SymbolCatalogue(provider).get()).symbols == ("BBCA",)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change",
    [
        {"next_page": 2},
        {"prev_page": 1},
        {"current_page": 2},
        {"total_page": 2},
        {"total_data": 2},
        {"total_data_in_page": 2},
        {"data_per_page": 0},
        {"unknown_cursor": "remaining"},
    ],
)
async def test_actual_provider_pagination_must_prove_one_complete_page(change):
    from app.reference.catalogue import SymbolCatalogue
    from app.reference.taxonomy import CatalogueError

    provider = TaxonomyProvider()
    provider.companies = {
        "data": [company("BBCA")],
        "pagination": {
            "next_page": 0,
            "prev_page": 0,
            "current_page": 1,
            "total_page": 1,
            "data_per_page": 10000,
            "total_data_in_page": 1,
            "total_data": 1,
        }
        | change,
    }
    with pytest.raises(CatalogueError):
        await SymbolCatalogue(provider).get()


@pytest.mark.parametrize(
    "nested", [{"success": False}, {"status": "error"}, {"error": "source failed"}]
)
def test_nested_provider_failure_never_becomes_positive_membership(nested):
    from app.reference.taxonomy import CatalogueError, company_symbols

    raw = {"data": {"companies": [company("BBCA")], **nested}}
    with pytest.raises(CatalogueError):
        company_symbols(TypeAdapter(JsonValue).validate_python(raw))


def test_inner_metadata_cannot_hide_outer_incomplete_count():
    from app.reference.taxonomy import CatalogueError, company_symbols

    raw = {"total": 2, "data": {"companies": [company("BBCA")], "total": 1}}
    with pytest.raises(CatalogueError):
        company_symbols(raw)
