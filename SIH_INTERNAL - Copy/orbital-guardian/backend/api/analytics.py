"""
Analytics endpoints — every number comes from the real database.
Empty datasets return explicit empty states, never fake data.
"""

from collections import Counter
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from backend.database.connection import get_db
from backend.database.models import AnalysisJob, Conjunction

router = APIRouter(prefix="/analytics", tags=["analytics"])

RISK_ORDER = ["CRITICAL", "HIGH", "MEDIUM", "LOW"]


def _db_unavailable(e: Exception):
    raise HTTPException(
        status_code=503,
        detail="Database unavailable. Analytics cannot be retrieved.",
    ) from e


def _classify(risk_score: int | None, risk_status: str) -> str:
    if risk_score is not None:
        if risk_score >= 80:
            return "CRITICAL"
        if risk_score >= 60:
            return "HIGH"
        if risk_score >= 30:
            return "MEDIUM"
        return "LOW"

    # Legacy records only carry the distance-based status.
    return risk_status if risk_status in RISK_ORDER else "UNCLASSIFIED"


@router.get("/summary")
def analytics_summary(
    days: int = Query(30, ge=1, le=365),
    db: Session = Depends(get_db),
):
    since = datetime.now(timezone.utc) - timedelta(days=days)

    try:
        events = (
            db.query(Conjunction)
            .filter(Conjunction.created_at >= since.replace(tzinfo=None))
            .all()
        )

        type_counter: Counter = Counter()

        # Object-type distribution from satellites table (heuristic typing).
        from backend.orbital.risk import infer_object_type
        from backend.database.models import Satellite

        for (name,) in db.query(Satellite.name).all():
            type_counter[infer_object_type(name)] += 1

        completed_jobs = (
            db.query(AnalysisJob)
            .filter(AnalysisJob.status == "COMPLETED")
            .count()
        )

        failed_jobs = (
            db.query(AnalysisJob).filter(AnalysisJob.status == "FAILED").count()
        )

        pairs_total = (
            db.query(func.coalesce(func.sum(AnalysisJob.pairs_processed), 0))
            .scalar()
            or 0
        )

        objects_analyzed = (
            db.query(
                func.count(func.distinct(Conjunction.satellite_a_norad_id))
            )
            .scalar()
            or 0
        )
    except HTTPException:
        raise
    except Exception as e:
        _db_unavailable(e)

    risk_dist = Counter(_classify(e.risk_score, e.risk_status) for e in events)

    high_priority = sum(v for k, v in risk_dist.items() if k in ("CRITICAL", "HIGH"))

    avg_confidence = None

    confidences = [
        e.confidence for e in events if e.confidence is not None
    ]

    if confidences:
        avg_confidence = round(sum(confidences) / len(confidences), 1)

    return {
        "window_days": days,
        "objects_analyzed": objects_analyzed,
        "payloads": type_counter.get("ACTIVE", 0),
        "debris": type_counter.get("DEBRIS", 0),
        "rocket_bodies": type_counter.get("ROCKET BODY", 0),
        "pairs_screened": int(pairs_total),
        "candidate_events": len(events),
        "high_priority_events": high_priority,
        "completed_analyses": completed_jobs,
        "failed_analyses": failed_jobs,
        "avg_confidence": avg_confidence,
        "risk_distribution": {k: risk_dist.get(k, 0) for k in
                              RISK_ORDER + ["UNCLASSIFIED"]},
    }


@router.get("/events-over-time")
def events_over_time(
    days: int = Query(30, ge=1, le=365),
    db: Session = Depends(get_db),
):
    since_date = (datetime.now(timezone.utc) - timedelta(days=days)).date()

    try:
        events = (
            db.query(Conjunction)
            .order_by(Conjunction.created_at.asc())
            .limit(5000)
            .all()
        )
    except HTTPException:
        raise
    except Exception as e:
        _db_unavailable(e)

    daily: dict[str, int] = {}

    for event in events:
        created = event.created_at

        if created is None:
            continue

        day = created.date()

        if day < since_date:
            continue

        key = day.isoformat()

        daily[key] = daily.get(key, 0) + 1

    series = [
        {"date": key, "count": count}
        for key, count in sorted(daily.items())
    ]

    if not series:
        return {"days": days, "series": [], "empty": True}

    return {"days": days, "series": series, "empty": False}


@router.get("/analysis-duration")
def analysis_duration(db: Session = Depends(get_db)):
    """
    Real analysis durations from job records.
    """

    try:
        jobs = (
            db.query(AnalysisJob)
            .filter(
                AnalysisJob.status.in_(["COMPLETED", "FAILED"]),
                AnalysisJob.started_at.isnot(None),
                AnalysisJob.completed_at.isnot(None),
            )
            .order_by(AnalysisJob.completed_at.desc())
            .limit(100)
            .all()
        )
    except HTTPException:
        raise
    except Exception as e:
        _db_unavailable(e)

    durations = []

    for job in jobs:
        seconds = (job.completed_at - job.started_at).total_seconds()

        durations.append({
            "job_ref": job.job_ref,
            "status": job.status,
            "duration_seconds": round(seconds, 2),
            "objects": job.object_count,
            "completed_at": job.completed_at.isoformat(),
        })

    if not durations:
        return {"jobs": [], "avg_duration_seconds": None, "empty": True}

    avg = round(
        sum(d["duration_seconds"] for d in durations) / len(durations), 2
    )

    return {
        "jobs": durations,
        "avg_duration_seconds": avg,
        "empty": False,
    }
