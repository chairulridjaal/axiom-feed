from fastapi import APIRouter, Depends

from app.core.security import verify_api_key
from app.providers.stockbit.transport import get_transport

router = APIRouter(dependencies=[Depends(verify_api_key)], tags=["Sectors"])


@router.get("/v1/sectors")
async def sectors():
    t = get_transport()
    try:
        data = await t.get_json("https://exodus.stockbit.com/emitten/sectors", label="sectors")
        return {"sectors": data.get("data") if isinstance(data, dict) and "data" in data else data}
    except Exception:
        return {"sectors": []}


@router.get("/v1/sectors/{sid}/subsectors")
async def subsectors(sid: str):
    t = get_transport()
    try:
        data = await t.get_json(
            f"https://exodus.stockbit.com/emitten/sectors/{sid}/subsectors",
            label=f"subsectors {sid}",
        )
        return {
            "sector": sid,
            "subsectors": data.get("data") if isinstance(data, dict) and "data" in data else [],
        }
    except Exception:
        return {"sector": sid, "subsectors": []}


@router.get("/v1/sectors/{sid}/subsectors/{subId}/companies")
async def sector_companies(sid: str, subId: str):
    t = get_transport()
    try:
        data = await t.get_json(
            f"https://exodus.stockbit.com/emitten/v3/sector/{sid}/subsector/{subId}/company",
            label=f"sector_companies {sid}/{subId}",
        )
        return {
            "sector": sid,
            "subsector": subId,
            "companies": data.get("data") if isinstance(data, dict) and "data" in data else [],
        }
    except Exception:
        return {"sector": sid, "subsector": subId, "companies": []}
