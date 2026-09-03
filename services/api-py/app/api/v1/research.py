"""Institutional Research, Morning Notes & Analyst Briefings router."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from app.core.security import verify_api_key
from app.providers.stockbit.provider import get_provider

router = APIRouter(dependencies=[Depends(verify_api_key)], tags=["Research"])


@router.get("/v1/research/morning-notes")
async def get_morning_notes(
    limit: int = Query(50, ge=1, le=100, description="Number of broadcast notes"),
    cursor_id: int | None = Query(None, description="Cursor ID for pagination"),
) -> dict[str, Any]:
    """Retrieve daily morning macro briefings, sector updates, and pre-market analyst notes from the official Stockbit Reports desk."""
    p = get_provider()
    try:
        data = await p.broadcast_messages(room_id=338965, limit=limit, cursor_id=cursor_id)
        raw_data = data.get("data") if isinstance(data, dict) else data
        return {
            "source": "Stockbit Reports (Broadcast 338965)",
            "data": raw_data,
        }
    except Exception as e:
        raise HTTPException(502, f"Failed to fetch morning notes: {e}")


@router.get("/v1/research/reports")
async def get_research_reports(
    account: str = Query("StockbitReports", description="Research publisher account"),
    last_stream_id: int = Query(0, description="Cursor for pagination"),
    limit: int = Query(20, ge=1, le=50, description="Number of reports to return"),
) -> dict[str, Any]:
    """Retrieve institutional equity research reports and thesis writeups published by an analyst account."""
    p = get_provider()
    try:
        data = await p.user_stream(
            username=account,
            category="STREAM_CATEGORY_MAIN_IDEAS",
            last_stream_id=last_stream_id,
            limit=limit,
        )
        raw_data = data.get("data") if isinstance(data, dict) else data
        return {
            "account": account,
            "data": raw_data,
        }
    except Exception as e:
        raise HTTPException(502, f"Failed to fetch research reports for {account}: {e}")


@router.get("/v1/research/reports/{post_id}")
async def get_research_report_detail(post_id: int) -> dict[str, Any]:
    """Retrieve complete research report article, thesis breakdown, PDF attachments, and analyst models."""
    p = get_provider()
    try:
        data = await p.stream_post(post_id=post_id)
        raw_data = data.get("data") if isinstance(data, dict) else data
        return {
            "post_id": post_id,
            "report": raw_data,
        }
    except Exception as e:
        raise HTTPException(502, f"Failed to fetch research report {post_id}: {e}")
