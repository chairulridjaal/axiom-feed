import logging

from fastapi import APIRouter, Depends, HTTPException, Path
from pydantic import JsonValue, TypeAdapter

from app.core.security import verify_api_key
from app.providers.stockbit.provider import get_provider
from app.reference.taxonomy import company_symbols, node_ids, taxonomy_rows
from app.reference.wire import WireJSON

logger = logging.getLogger(__name__)
_JSON = TypeAdapter(JsonValue)

router = APIRouter(dependencies=[Depends(verify_api_key)], tags=["Sectors"])


@router.get("/v1/sectors")
async def sectors():
    from app.infra.upstream_cache import cached_json

    p = get_provider()

    async def _produce():
        try:
            response = await p.sector_list(max_bytes=1_000_000)
            data = (
                response.data if isinstance(response, WireJSON) else _JSON.validate_python(response)
            )
            rows = taxonomy_rows(data, "sectors")
            if rows:
                node_ids(data, "sectors")
            return {
                "sectors": data.get("data") if isinstance(data, dict) and "data" in data else data
            }
        except Exception as exc:
            logger.error("Taxonomy source unavailable", extra={"error_type": type(exc).__name__})
            raise HTTPException(status_code=503, detail="Sector source unavailable") from exc

    return await cached_json("sectors:list", _produce)


@router.get("/v1/sectors/{sid}/subsectors")
async def subsectors(sid: str = Path(pattern=r"^[A-Za-z0-9_-]{1,64}$")):
    from app.infra.upstream_cache import cached_json

    p = get_provider()

    async def _produce():
        try:
            response = await p.subsectors(sid, max_bytes=1_000_000)
            data = (
                response.data if isinstance(response, WireJSON) else _JSON.validate_python(response)
            )
            rows = taxonomy_rows(data, "subsectors")
            if rows:
                node_ids(data, "subsectors")
            return {
                "sector": sid,
                "subsectors": data.get("data") if isinstance(data, dict) and "data" in data else [],
            }
        except Exception as exc:
            logger.error("Taxonomy source unavailable", extra={"error_type": type(exc).__name__})
            raise HTTPException(status_code=503, detail="Subsector source unavailable") from exc

    return await cached_json(f"sectors:{sid}:subsectors", _produce)


@router.get("/v1/sectors/{sid}/subsectors/{subId}/companies")
async def sector_companies(
    sid: str = Path(pattern=r"^[A-Za-z0-9_-]{1,64}$"),
    subId: str = Path(pattern=r"^[A-Za-z0-9_-]{1,64}$"),
):
    from app.infra.upstream_cache import cached_json

    p = get_provider()

    async def _produce():
        try:
            response = await p.sector_companies(sid, subId, max_bytes=1_000_000)
            data = (
                response.data if isinstance(response, WireJSON) else _JSON.validate_python(response)
            )
            company_symbols(data)
            return {
                "sector": sid,
                "subsector": subId,
                "companies": data.get("data") if isinstance(data, dict) and "data" in data else [],
            }
        except Exception as exc:
            logger.error("Taxonomy source unavailable", extra={"error_type": type(exc).__name__})
            raise HTTPException(
                status_code=503, detail="Company taxonomy source unavailable"
            ) from exc

    return await cached_json(f"sectors:{sid}:{subId}:companies", _produce)
