"""Bounded atomic snapshots of positive provider-taxonomy symbol membership."""

import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from typing import Literal, Protocol

import orjson
from pydantic import BaseModel, ConfigDict, JsonValue

from app.infra.singleflight import Singleflight
from app.reference.equity_roots import reviewed_equity_roots
from app.reference.taxonomy import CatalogueError, company_symbols, node_ids, taxonomy_rows
from app.reference.wire import WireJSON


class TaxonomyProvider(Protocol):
    async def sector_list(self, *, max_bytes: int) -> WireJSON | JsonValue: ...
    async def subsectors(self, sid: str, *, max_bytes: int) -> WireJSON | JsonValue: ...
    async def sector_companies(
        self, sid: str, sub_id: str, *, max_bytes: int
    ) -> WireJSON | JsonValue: ...


@dataclass(frozen=True, slots=True)
class CatalogueLimits:
    max_calls: int = 256
    max_rows: int = 20_000
    max_bytes: int = 10_000_000
    max_response_bytes: int = 1_000_000
    timeout_seconds: float = 45.0
    ttl_seconds: float = 1800.0


class SymbolSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True)
    source: Literal["stockbit_sector_taxonomy"] = "stockbit_sector_taxonomy"
    scope: Literal["provider_equity_sector_taxonomy"] = "provider_equity_sector_taxonomy"
    fetched_at: datetime
    complete: Literal[True] = True
    count: int
    symbols: tuple[str, ...]
    checksum: str


class SymbolCatalogue:
    """Own one mutable cache slot; only successful immutable snapshots enter it."""

    def __init__(
        self,
        provider: TaxonomyProvider | Callable[[], TaxonomyProvider],
        limits: CatalogueLimits = CatalogueLimits(),
        *,
        clock: Callable[[], float] = time.monotonic,
    ):
        self._provider = provider
        self._limits = limits
        self._clock = clock
        self._expires = 0.0
        self.last_success: SymbolSnapshot | None = None
        self._flight: Singleflight[SymbolSnapshot] = Singleflight(limits.timeout_seconds)

    async def get(self) -> SymbolSnapshot:
        if self.last_success is not None and self._clock() < self._expires:
            return self.last_success
        return await self._flight.do("symbol_catalogue", self._refresh)

    async def _refresh(self) -> SymbolSnapshot:
        provider = self._provider() if callable(self._provider) else self._provider
        calls = rows = byte_count = 0

        async def fetch(
            kind: Literal["sectors", "subsectors", "companies"],
            sector: str = "",
            subsector: str = "",
        ) -> JsonValue:
            nonlocal calls, rows, byte_count
            calls += 1
            if calls > self._limits.max_calls:
                raise CatalogueError("Taxonomy call budget exceeded")
            bound = min(self._limits.max_response_bytes, self._limits.max_bytes - byte_count)
            if bound <= 0:
                raise CatalogueError("Taxonomy byte budget exceeded")
            match kind:
                case "sectors":
                    raw = await provider.sector_list(max_bytes=bound)
                case "subsectors":
                    raw = await provider.subsectors(sector, max_bytes=bound)
                case "companies":
                    raw = await provider.sector_companies(sector, subsector, max_bytes=bound)
            if isinstance(raw, WireJSON):
                byte_count += raw.byte_count
                raw = raw.data
            else:
                # In-memory fixtures have no transport; production always returns WireJSON.
                byte_count += len(orjson.dumps(raw))
            rows += len(taxonomy_rows(raw, kind))
            if byte_count > self._limits.max_bytes or rows > self._limits.max_rows:
                raise CatalogueError("Taxonomy aggregate budget exceeded")
            return raw

        symbols: set[str] = set()
        for sector in reviewed_equity_roots(await fetch("sectors")):
            try:
                subsectors = node_ids(await fetch("subsectors", sector), "subsectors")
            except CatalogueError as exc:
                raise CatalogueError(f"Invalid subsectors for sector {sector}: {exc}") from exc
            for subsector in subsectors:
                symbols.update(company_symbols(await fetch("companies", sector, subsector)))
        if not symbols:
            raise CatalogueError("Empty provider symbol taxonomy")
        ordered = tuple(sorted(symbols))
        snapshot = SymbolSnapshot(
            fetched_at=datetime.now(UTC),
            count=len(ordered),
            symbols=ordered,
            checksum=sha256("\n".join(ordered).encode()).hexdigest(),
        )
        self.last_success = snapshot
        self._expires = self._clock() + self._limits.ttl_seconds
        return snapshot
