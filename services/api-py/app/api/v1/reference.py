"""Reference data remains factual, scoped, authenticated, and fail-closed."""

import logging

import httpx
from fastapi import APIRouter, Depends, HTTPException

from app.core.security import verify_api_key
from app.providers.stockbit.provider import get_provider
from app.reference.catalogue import SymbolCatalogue, SymbolSnapshot
from app.reference.taxonomy import CatalogueError

logger = logging.getLogger(__name__)
router = APIRouter(dependencies=[Depends(verify_api_key)], tags=["Reference"])
catalogue = SymbolCatalogue(get_provider)


@router.get("/v1/reference/symbols", response_model=SymbolSnapshot)
async def symbols() -> SymbolSnapshot:
    try:
        return await catalogue.get()
    except (CatalogueError, httpx.HTTPError, TimeoutError, RuntimeError) as exc:
        logger.error(
            "Symbol catalogue unavailable",
            extra={
                "error_type": type(exc).__name__,
                "reason": str(exc) if isinstance(exc, CatalogueError) else "source unavailable",
            },
        )
        raise HTTPException(status_code=503, detail="Symbol catalogue unavailable") from exc
