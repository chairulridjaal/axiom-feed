from fastapi import APIRouter, Depends

from app.core.security import verify_api_key
from app.providers.stockbit.provider import get_provider

router = APIRouter(dependencies=[Depends(verify_api_key)], tags=["Sectors"])


@router.get("/v1/sectors")
async def sectors():
    p = get_provider()
    try:
        data = await p.sector_list()
        return {"sectors": data.get("data") if isinstance(data, dict) and "data" in data else data}
    except Exception:
        return {"sectors": []}


@router.get("/v1/sectors/{sid}/subsectors")
async def subsectors(sid: str):
    p = get_provider()
    try:
        data = await p.subsectors(sid)
        return {
            "sector": sid,
            "subsectors": data.get("data") if isinstance(data, dict) and "data" in data else [],
        }
    except Exception:
        return {"sector": sid, "subsectors": []}


@router.get("/v1/sectors/{sid}/subsectors/{subId}/companies")
async def sector_companies(sid: str, subId: str):
    p = get_provider()
    try:
        data = await p.sector_companies(sid, subId)
        return {
            "sector": sid,
            "subsector": subId,
            "companies": data.get("data") if isinstance(data, dict) and "data" in data else [],
        }
    except Exception:
        return {"sector": sid, "subsector": subId, "companies": []}
