"""
Analysis job endpoints with Server-Sent Events progress streaming.

POST /analysis/start                — submit a screening job (ANALYST+)
GET  /analysis/{job_ref}            — current job state snapshot
GET  /analysis/{job_ref}/progress   — SSE stream of REAL pipeline events
GET  /analysis/jobs                 — recent jobs (ADMIN monitoring)
"""

import asyncio
import json
import queue

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from backend.api.dependencies import get_current_user, require_role, require_user
from backend.database.connection import SessionLocal, get_db
from backend.database.models import AnalysisJob as AnalysisJobRecord
from backend.jobs.manager import manager

router = APIRouter(prefix="/analysis", tags=["analysis"])


class AnalysisStartRequest(BaseModel):
    objects: list[int] = Field(..., description="NORAD IDs to screen")

    horizon_hours: float = Field(24, gt=0, le=72)

    step_minutes: int = Field(10, gt=0, le=60)

    screen_threshold_km: float = Field(
        25.0, gt=0, le=500,
        description="Broad-phase filter radius. NOT a collision threshold.",
    )

    top_n: int = Field(20, gt=0, le=100)


@router.post("/start")
def start_analysis(
    request: AnalysisStartRequest,
    user=Depends(require_role("ANALYST")),
):
    """
    Submit an asynchronous conjunction-screening job.
    Progress is streamed via GET /analysis/{job_ref}/progress.
    """

    norad_ids = list(dict.fromkeys(request.objects))

    if len(norad_ids) < 2:
        raise HTTPException(
            status_code=400,
            detail="At least two distinct objects are required.",
        )

    if len(norad_ids) > 50:
        raise HTTPException(
            status_code=400, detail="Maximum 50 objects per screening run."
        )

    handle = manager.submit(
        norad_ids=norad_ids,
        horizon_hours=request.horizon_hours,
        step_minutes=request.step_minutes,
        screen_threshold_km=request.screen_threshold_km,
        top_n=request.top_n,
        user_id=user.id if user else None,
    )

    return {
        "job_ref": handle.job_ref,
        "status": handle.status,
        "progress_url": f"/analysis/{handle.job_ref}/progress",
        "state_url": f"/analysis/{handle.job_ref}",
    }


@router.get("/jobs")
def list_jobs(
    limit: int = Query(20, gt=0, le=100),
    offset: int = Query(0, ge=0),
    _admin=Depends(require_role("ADMIN")),
    db=Depends(get_db),
):
    """Recent analysis jobs for system monitoring (ADMIN)."""

    total = db.query(AnalysisJobRecord).count()

    records = (
        db.query(AnalysisJobRecord)
        .order_by(AnalysisJobRecord.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )

    return {
        "total": total,
        "jobs": [
            {
                "job_ref": r.job_ref,
                "status": r.status,
                "stage": r.current_stage,
                "progress": r.progress_percentage,
                "objects": r.object_count,
                "pairs_total": r.pairs_total,
                "pairs_processed": r.pairs_processed,
                "candidates": r.candidates_found,
                "started_at": r.started_at.isoformat() if r.started_at else None,
                "completed_at": (
                    r.completed_at.isoformat() if r.completed_at else None
                ),
                "error": r.error_message[:200] if r.error_message else None,
            }
            for r in records
        ],
    }


@router.get("/{job_ref}")
def job_state(job_ref: str):
    handle = manager.get(job_ref)

    if handle is None:
        # Check DB history for finished/restared-over jobs.
        db = SessionLocal()

        try:
            record = (
                db.query(AnalysisJobRecord)
                .filter(AnalysisJobRecord.job_ref == job_ref)
                .first()
            )

            if record is None:
                raise HTTPException(status_code=404, detail="Unknown job.")

            return {
                "job_ref": record.job_ref,
                "status": record.status,
                "stage": record.current_stage,
                "progress_percentage": record.progress_percentage,
                "counters": {
                    "pairs_total": record.pairs_total,
                    "pairs_processed": record.pairs_processed,
                    "candidates_found": record.candidates_found,
                    "events_completed": record.events_completed,
                },
                "result": record.result_summary,
                "error": record.error_message,
                "source": "database_history",
            }
        finally:
            db.close()

    return {"source": "live", **handle.snapshot()}


@router.get("/{job_ref}/progress")
async def job_progress(job_ref: str, timeout_seconds: int = Query(600, gt=0, le=3600)):
    """
    Server-Sent Events stream of actual pipeline events.
    Each event carries the real stage, counters and timings.
    """

    handle = manager.get(job_ref)

    if handle is None:
        raise HTTPException(status_code=404, detail="Unknown or expired job.")

    q = handle.subscribe()

    async def event_stream():
        sent_terminal = False

        try:
            while not sent_terminal:
                try:
                    event = await asyncio.wait_for(
                        asyncio.to_thread(q.get, True, 5), timeout=6
                    )
                except (TimeoutError, asyncio.TimeoutError):
                    # Heartbeat keeps connections alive through proxies.
                    yield ": heartbeat\n\n"
                    continue

                payload = {k: v for k, v in event.items()}

                yield f"data: {json.dumps(payload, default=str)}\n\n"

                if payload.get("type") in ("completed", "failed"):
                    sent_terminal = True

        finally:
            handle.unsubscribe(q)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
