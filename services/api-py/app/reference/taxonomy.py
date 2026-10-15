"""Strict provider-taxonomy parsing. Completeness never implies an IDX directory."""

import re
from typing import Final, Literal

from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    ValidationError,
    field_validator,
)


class CatalogueError(Exception):
    """A source tree cannot be safely published as one complete snapshot."""


class TaxonomyNode(BaseModel):
    model_config = ConfigDict(frozen=True)
    id: str = Field(
        validation_alias=AliasChoices("id", "sector_id", "subsector_id", "sub_sector_id")
    )

    @field_validator("id", mode="before")
    @classmethod
    def source_identifier(cls, value: JsonValue) -> str:
        match value:
            case str():
                text = value
            case int() if not isinstance(value, bool):
                text = str(value)
            case _:
                raise CatalogueError("Invalid taxonomy identifier")
        if re.fullmatch(r"[A-Za-z0-9_-]{1,64}", text) is None:
            raise CatalogueError("Unsafe taxonomy identifier")
        return text


class TaxonomyCompany(BaseModel):
    model_config = ConfigDict(frozen=True)
    symbol: str = Field(validation_alias=AliasChoices("symbol", "stock_code", "code"))

    type_company: str = Field(min_length=1)
    country: str | None = None
    company_status: str | None = None

    def is_active_indonesian_equity(self) -> bool:
        if self.type_company != "Saham":
            return False
        if self.country is None or self.company_status is None:
            raise CatalogueError("Equity classification is incomplete")
        return self.country == "ID" and self.company_status == "STATUS_ACTIVE"

    @field_validator("symbol")
    @classmethod
    def equity_symbol(cls, value: str) -> str:
        text = value.strip().upper()
        if not text or len(text) > 64:
            raise CatalogueError("Invalid taxonomy company symbol")
        return text


_TOTAL_KEYS: Final = frozenset(
    {"total", "total_count", "total_data", "total_data_in_page", "count"}
)
_NEXT_KEYS: Final = frozenset(
    {"next", "next_page", "nextPage", "has_more", "has_next", "has_next_page"}
)
_PAGE_KEYS: Final = frozenset({"page", "current_page", "total_pages", "total_page", "last_page"})


def _pagination(metadata: dict[str, JsonValue], row_count: int) -> None:
    if (
        metadata.get("success") is False
        or metadata.get("error")
        or metadata.get("status") in ("error", "failed", "failure")
    ):
        raise CatalogueError("Provider taxonomy failed")
    known = _TOTAL_KEYS | _NEXT_KEYS | _PAGE_KEYS
    for key, value in metadata.items():
        if key not in known and key not in {
            "pagination",
            "meta",
            "message",
            "status",
            "success",
            "error",
            "prev_page",
            "data_per_page",
        }:
            raise CatalogueError("Unrecognized taxonomy metadata")
        if key == "prev_page" and (type(value) is not int or value != 0):
            raise CatalogueError("Taxonomy has a previous page")
        if key == "data_per_page" and (
            type(value) is not int or value < max(1, row_count) or "total_data" not in metadata
        ):
            raise CatalogueError("Taxonomy page size is unverifiable")
        if key in _NEXT_KEYS and value not in (None, False, 0, ""):
            raise CatalogueError("Paginated taxonomy is incomplete")
        if key in _TOTAL_KEYS and (type(value) is not int or value != row_count):
            raise CatalogueError("Taxonomy count does not match rows")
        if key in _PAGE_KEYS and (type(value) is not int or value not in (0, 1)):
            raise CatalogueError("Multiple taxonomy pages are unsupported")
        if key in ("pagination", "meta"):
            if not isinstance(value, dict):
                raise CatalogueError("Invalid taxonomy pagination metadata")
            if key == "pagination" and not any(k in _TOTAL_KEYS for k in value):
                raise CatalogueError("Unverifiable taxonomy pagination")
            _pagination(value, row_count)


def taxonomy_rows(
    raw: JsonValue, kind: Literal["sectors", "subsectors", "companies"]
) -> list[JsonValue]:
    """Extract one explicitly complete list; ambiguous or truncated envelopes fail."""
    if not isinstance(raw, dict) or "data" not in raw:
        raise CatalogueError("Missing taxonomy data")
    if (
        raw.get("success") is False
        or raw.get("error")
        or raw.get("status") in ("error", "failed", "failure")
    ):
        raise CatalogueError("Provider taxonomy failed")
    data = raw["data"]
    metadata = [{key: value for key, value in raw.items() if key != "data"}]
    if isinstance(data, dict):
        keys = (kind, "company") if kind == "companies" else (kind,)
        matches = [key for key in keys if key in data]
        if len(matches) != 1:
            raise CatalogueError("Unknown taxonomy list shape")
        list_key = matches[0]
        metadata.append({key: value for key, value in data.items() if key != list_key})
        data = data[list_key]
    if not isinstance(data, list):
        raise CatalogueError("Invalid taxonomy list")
    for layer in metadata:
        _pagination(layer, len(data))
    return data


def node_ids(raw: JsonValue, kind: Literal["sectors", "subsectors"]) -> tuple[str, ...]:
    try:
        values = tuple(TaxonomyNode.model_validate(row).id for row in taxonomy_rows(raw, kind))
    except ValidationError as exc:
        raise CatalogueError("Invalid taxonomy node") from exc
    if not values or len(set(values)) != len(values):
        raise CatalogueError("Empty or duplicate taxonomy branches")
    return values


def company_symbols(raw: JsonValue) -> tuple[str, ...]:
    try:
        companies = tuple(
            TaxonomyCompany.model_validate(row) for row in taxonomy_rows(raw, "companies")
        )
        symbols = tuple(
            company.symbol for company in companies if company.is_active_indonesian_equity()
        )
        if any(re.fullmatch(r"[A-Z]{2,5}", symbol) is None for symbol in symbols):
            raise CatalogueError("Invalid equity symbol")
        return symbols
    except ValidationError as exc:
        raise CatalogueError("Invalid taxonomy company") from exc
