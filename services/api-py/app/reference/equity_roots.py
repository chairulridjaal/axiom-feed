"""Reviewed Stockbit equity-sector IDs, not a complete IDX security directory."""

from typing import Final, Literal

from pydantic import Field, JsonValue, ValidationError

from app.reference.taxonomy import CatalogueError, TaxonomyNode, node_ids, taxonomy_rows

EQUITY_ROOT_IDS: Final = ("1", "2", "3", "4", "5", "6", "7", "8", "9", "50", "51")


class EquityRoot(TaxonomyNode):
    name: str = Field(min_length=1)
    parent: Literal[""] = ""
    symbol: Literal[""] = ""


def reviewed_equity_roots(raw: JsonValue) -> tuple[str, ...]:
    present = node_ids(raw, "sectors")
    if not set(EQUITY_ROOT_IDS).issubset(present):
        raise CatalogueError("Reviewed equity sector roots are missing")
    try:
        for row in taxonomy_rows(raw, "sectors"):
            node = TaxonomyNode.model_validate(row)
            if node.id in EQUITY_ROOT_IDS:
                EquityRoot.model_validate(row)
    except ValidationError as exc:
        raise CatalogueError("Reviewed equity root metadata is invalid") from exc
    return EQUITY_ROOT_IDS
