"""
Object intelligence endpoints.
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_
from sqlalchemy.orm import Session

from backend.database.connection import get_db
from backend.database.models import Conjunction
from backend.intelligence.object_profile import build_object_profile
from backend.orbital.data_fetcher import CATALOG_GROUPS, fetch_catalog

router = APIRouter(prefix="/objects", tags=["objects"])


@router.get("")
def list_objects(
    group: str = Query("visual", description=f"CelesTrak group: {', '.join(CATALOG_GROUPS)}"),
    limit: int = Query(50, gt=0, le=200),
    search: str | None = Query(None, max_length=80),
):
    """
    Browse tracked objects from the live catalog with
    optional name filtering. Serves stale data when the
    upstream provider is unavailable.
    """

    try:
        objects = fetch_catalog(group=group, limit=200)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception:
        raise HTTPException(
            status_code=503,
            detail="Orbital data provider temporarily unavailable. "
            "Try again shortly.",
        )

    if search:
        needle = search.lower()
        objects = [o for o in objects if needle in o["name"].lower()]

    return {
        "group": group,
        "description": CATALOG_GROUPS.get(group),
        "count": len(objects[:limit]),
        "objects": [
            {
                "norad_id": o["norad_id"],
                "name": o["name"],
                "object_type_hint": _type_hint(o["name"]),
            }
            for o in objects[:limit]
        ],
    }


def _type_hint(name: str) -> str:
    upper = name.upper()
    if " DEB" in upper or upper.endswith("DEB"):
        return "DEBRIS"
    if "R/B" in upper:
        return "ROCKET BODY"
    return "PAYLOAD/ACTIVE"


@router.get("/{norad_id}/profile")
def object_profile(norad_id: int, db: Session = Depends(get_db)):
    """
    Unified Object Intelligence profile:
    identity, mission, live orbit, data quality,
    conjunction context and source transparency.
    """

    try:
        profile = build_object_profile(norad_id, db=db)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    return profile


@router.get("/{norad_id}/trajectory")
def object_trajectory(
    norad_id: int,
    hours: float = Query(24, gt=0, le=72),
    step_minutes: int = Query(10, gt=0, le=60),
):
    """SGP4 trajectory for one object (deterministic)."""

    from backend.api.app import load_satellites  # shared helper

    start_time, satellites = load_satellites([norad_id])

    satellite = satellites[0]

    from backend.orbital.trajectory import generate_trajectory

    try:
        trajectory = generate_trajectory(
            satellite["satellite"],
            start_time,
            hours=hours,
            step_minutes=step_minutes,
        )
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))

    return {
        "norad_id": norad_id,
        "name": satellite["name"],
        "tle_epoch": satellite.get("tle_epoch"),
        "start_time": start_time.isoformat(),
        "horizon_hours": hours,
        "step_minutes": step_minutes,
        "points": [
            {
                "time": p["time"].isoformat(),
                "position": {"x": p["position"][0], "y": p["position"][1],
                             "z": p["position"][2]},
                "velocity": {"x": p["velocity"][0], "y": p["velocity"][1],
                             "z": p["velocity"][2]},
            }
            for p in trajectory
        ],
    }


@router.get("/{norad_id}/conjunctions")
def object_conjunctions(norad_id: int, db: Session = Depends(get_db)):
    """All recorded conjunction events involving this object."""

    records = (
        db.query(Conjunction)
        .filter(
            or_(
                Conjunction.satellite_a_norad_id == norad_id,
                Conjunction.satellite_b_norad_id == norad_id,
            )
        )
        .order_by(Conjunction.tca.desc())
        .limit(100)
        .all()
    )

    now = datetime.now(timezone.utc)

    return {
        "norad_id": norad_id,
        "count": len(records),
        "events": [
            {
                "id": r.id,
                "other_norad_id": (
                    r.satellite_b_norad_id
                    if r.satellite_a_norad_id == norad_id
                    else r.satellite_a_norad_id
                ),
                "tca": r.tca.isoformat(),
                "upcoming": r.tca >= now,
                "minimum_distance_km": r.minimum_distance_km,
                "relative_velocity_km_s": r.relative_velocity_km_s,
                "risk_status": r.risk_status,
                "risk_score": r.risk_score,
            }
            for r in records
        ],
    }


@router.post("/{norad_id}/refresh")
def refresh_profile(norad_id: int, db: Session = Depends(get_db)):
    """Force a fresh profile build, bypassing the cache."""
    try:
        profile = build_object_profile(norad_id, db=db, use_cache=False)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))

    return profile
