"""
Conjunction event detail endpoints.

GET /conjunctions/{event_id}           — full event record
GET /conjunctions/{event_id}/risk      — explainable risk breakdown
GET /conjunctions/{event_id}/timeline  — encounter replay timeline data
"""

from datetime import timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from backend.config import ai_configured
from backend.database.connection import get_db
from backend.database.models import Conjunction as ConjunctionRecord
from backend.orbital.conjunction import calculate_distance
from backend.orbital.data_fetcher import fetch_tle
from backend.orbital.propagator import propagate
from backend.orbital.tle_parser import parse_tle

router = APIRouter(prefix="/conjunctions", tags=["conjunctions"])


def _load_event(event_id: int, db: Session) -> ConjunctionRecord:
    record = db.query(ConjunctionRecord).filter(
        ConjunctionRecord.id == event_id
    ).first()

    if record is None:
        raise HTTPException(status_code=404, detail="Conjunction event not found.")

    return record


@router.get("/{event_id}")
def event_detail(event_id: int, db: Session = Depends(get_db)):
    r = _load_event(event_id, db)

    return {
        "id": r.id,
        "forecast_id": r.forecast_id,
        "object_a": {"norad_id": r.satellite_a_norad_id},
        "object_b": {"norad_id": r.satellite_b_norad_id},
        "tca": r.tca.isoformat(),
        "minimum_distance_km": r.minimum_distance_km,
        "coarse_tca": r.coarse_tca.isoformat() if r.coarse_tca else None,
        "coarse_distance_km": r.coarse_distance_km,
        "relative_velocity_km_s": r.relative_velocity_km_s,
        "risk_status": r.risk_status,
        "risk_score": r.risk_score,
        "risk_factors": r.risk_factors,
        "confidence": r.confidence,
        "refined": r.refined,
        "created_at": r.created_at.isoformat(),
        # Object names resolved lazily by the frontend via /objects profile;
        # included here when satellites are already cataloged.
        "_names": _resolve_names(db, [r.satellite_a_norad_id,
                                      r.satellite_b_norad_id]),
    }


def _resolve_names(db, norad_ids):
    from backend.database.models import Satellite

    names = {}

    for nid in norad_ids:
        rec = db.query(Satellite).filter(Satellite.norad_id == nid).first()

        if rec:
            names[str(nid)] = rec.name

    return names


@router.get("/{event_id}/risk")
def event_risk(event_id: int, db: Session = Depends(get_db)):
    """
    Explainable Operational Risk Priority breakdown.
    The score itself is deterministic (stored at analysis time);
    this endpoint surfaces the factor contributions verbatim.
    """

    from backend.rag.copilot import explain_event_deterministic

    r = _load_event(event_id, db)

    factors = r.risk_factors or {}

    weights = factors.get("weights", {})

    contributions = []

    for label, factor_key, weight_key in [
        ("Miss Distance", "distance_factor", "distance"),
        ("Relative Velocity", "relative_velocity_factor", "relative_velocity"),
        ("Time Urgency", "time_to_tca_factor", "time_to_tca"),
        ("Object Criticality", "object_type_factor", "object_type"),
    ]:
        factor_value = factors.get(factor_key, 0)
        weight = weights.get(weight_key, 0)
        max_points = round(weight * 100)

        contributions.append({
            "factor": label,
            "factor_value": factor_value,
            "weight": weight,
            "earned": round(factor_value * weight * 100),
            "max": max_points,
        })

    return {
        "conjunction_id": r.id,
        "risk_score": r.risk_score,
        "risk_level": r.risk_status,
        "label": "OPERATIONAL RISK PRIORITY",
        "disclaimer": (
            "Heuristic screening priority — NOT a probability of collision."
        ),
        "contributions": contributions,
        "confidence": r.confidence,
        "deterministic_explanation": explain_event_deterministic({
            "minimum_distance_km": r.minimum_distance_km,
            "relative_velocity_km_s": r.relative_velocity_km_s,
            "risk_score": r.risk_score,
            "risk_level": r.risk_status,
            "risk_factors": factors,
        }),
        "ai_explanation_available": ai_configured,
    }


@router.get("/{event_id}/timeline")
def event_timeline(
    event_id: int,
    window_minutes: int = Query(30, ge=5, le=60,
                                description="Half-window around TCA"),
    step_seconds: int = Query(60, ge=10, le=300),
    db: Session = Depends(get_db),
):
    """
    Encounter replay timeline: real SGP4 positions/velocities for both
    objects from (TCA - window) to (TCA + window), plus the live
    separation at each step. Fully deterministic.
    """

    from datetime import timedelta  # noqa: PLC0415

    r = _load_event(event_id, db)

    tca = r.tca

    if tca.tzinfo is None:
        tca = tca.replace(tzinfo=timezone.utc)

    try:
        tle_a = fetch_tle(r.satellite_a_norad_id)
        tle_b = fetch_tle(r.satellite_b_norad_id)
    except Exception as e:
        raise HTTPException(
            status_code=502, detail=f"TLE provider unavailable: {e}"
        )

    try:
        sat_a = parse_tle(tle_a["name"], tle_a["line1"], tle_a["line2"])
        sat_b = parse_tle(tle_b["name"], tle_b["line1"], tle_b["line2"])
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Invalid TLE data: {e}")

    start = tca - timedelta(minutes=window_minutes)
    end = tca + timedelta(minutes=window_minutes)

    steps = []
    current = start

    while current <= end:
        pos_a, vel_a = propagate(sat_a["satellite"], current)
        pos_b, vel_b = propagate(sat_b["satellite"], current)

        separation = calculate_distance(pos_a, pos_b)

        steps.append({
            "time": current.isoformat(),
            "seconds_to_tca": round((current - tca).total_seconds()),
            "position_a": {"x": pos_a[0], "y": pos_a[1], "z": pos_a[2]},
            "position_b": {"x": pos_b[0], "y": pos_b[1], "z": pos_b[2]},
            "separation_km": round(separation, 4),
            "is_tca": abs((current - tca).total_seconds()) < step_seconds / 2,
        })

        current += timedelta(seconds=step_seconds)

    return {
        "conjunction_id": r.id,
        "tca": tca.isoformat(),
        "window_minutes": window_minutes,
        "step_seconds": step_seconds,
        "object_a_norad_id": r.satellite_a_norad_id,
        "object_b_norad_id": r.satellite_b_norad_id,
        "object_a_name": sat_a["name"],
        "object_b_name": sat_b["name"],
        "minimum_distance_km": r.minimum_distance_km,
        "relative_velocity_km_s": r.relative_velocity_km_s,
        "steps": steps,
    }
