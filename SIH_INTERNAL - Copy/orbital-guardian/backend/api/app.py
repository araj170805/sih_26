import time
from datetime import datetime, timezone
from itertools import combinations

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.config import APP_ENV, FRONTEND_URL, feature_flags
from backend.database.connection import get_db
from backend.database.models import Conjunction as ConjunctionRecord
from backend.database.models import Forecast as ForecastRecord
from backend.database.models import Satellite as SatelliteRecord
from backend.orbital.conjunction import find_closest_approach
from backend.orbital.data_fetcher import CATALOG_GROUPS, fetch_catalog, fetch_tle
from backend.orbital.tle_parser import parse_tle
from backend.orbital.trajectory import generate_trajectory
from backend.services.analysis_service import (
    ProgressReporter,
    run_screening_pipeline,
)

# ==========================================
# FEATURE ROUTERS
# ==========================================

from backend.api.ai import router as ai_router
from backend.api.analytics import router as analytics_router
from backend.api.analysis import router as analysis_router
from backend.api.auth import router as auth_router
from backend.api.conjunctions import router as conjunctions_router
from backend.api.notifications import router as notifications_router
from backend.api.objects import router as objects_router
from backend.api.reports import router as reports_router
from backend.api.system import router as system_router
from backend.api.watchlists import router as watchlists_router

app = FastAPI(
    title="Orbital Guardian API",
    description=(
        "SGP4-based satellite trajectory and conjunction analysis "
        "with object intelligence, live analysis pipelines and an "
        "explainable AI copilot layer."
    ),
    version="2.0.0",
)


# ==========================================
# CORS
# ==========================================
#
# Locked down when FRONTEND_URL is configured;
# open during local development for convenience.

_origins = ["*"] if FRONTEND_URL in ("*", None) else [FRONTEND_URL]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ==========================================
# ROUTER MOUNTING
# ==========================================
# Existing v1 endpoints below are preserved verbatim.

for router in (
    auth_router,
    objects_router,
    analysis_router,
    conjunctions_router,
    watchlists_router,
    notifications_router,
    analytics_router,
    system_router,
    ai_router,
    reports_router,
):
    app.include_router(router)


# ==========================================
# REQUEST MODEL
# ==========================================


class ForecastRequest(BaseModel):
    objects: list[int] = Field(..., description="NORAD IDs of satellites")

    horizon_hours: float = Field(24, gt=0, le=72)

    step_minutes: int = Field(1, gt=0, le=60)


class ScreenRequest(BaseModel):
    objects: list[int] = Field(..., description="NORAD IDs to screen for conjunctions")

    horizon_hours: float = Field(24, gt=0, le=72)

    step_minutes: int = Field(10, gt=0, le=60)

    screen_threshold_km: float = Field(
        25.0,
        gt=0,
        le=500,
        description=(
            "Broad-phase screening radius. Pairs whose "
            "sampled minimum distance exceeds this are "
            "not refined. NOT a collision threshold."
        ),
    )

    top_n: int = Field(20, gt=0, le=100, description="Maximum events returned")


# ==========================================
# DATABASE HELPERS
# ==========================================


def upsert_satellite(db: Session, norad_id: int, name: str):

    record = (
        db.query(SatelliteRecord).filter(SatelliteRecord.norad_id == norad_id).first()
    )

    if record is None:
        record = SatelliteRecord(norad_id=norad_id, name=name)

        db.add(record)

    elif record.name != name:
        record.name = name

    return record


def load_satellites(norad_ids: list[int]):
    """
    Fetch TLEs and parse them into SGP4 objects.
    Shared by /forecast and /conjunction.
    """

    start_time = datetime.now(timezone.utc)

    satellites = []

    for norad_id in norad_ids:
        try:
            tle = fetch_tle(norad_id)

        except ValueError:
            # CelesTrak returns no data for
            # unknown / invalid NORAD IDs.
            raise HTTPException(
                status_code=404,
                detail=f"No TLE data found for NORAD {norad_id}. "
                "Check that the ID is valid.",
            )

        except Exception as e:
            raise HTTPException(
                status_code=502, detail=f"Failed to fetch NORAD {norad_id}: {e!s}"
            )

        try:
            satellite = parse_tle(tle["name"], tle["line1"], tle["line2"])

        except Exception as e:
            raise HTTPException(
                status_code=502, detail=f"Invalid TLE data for NORAD {norad_id}: {e!s}"
            )

        # TLE epoch for data-freshness reporting.
        try:
            from datetime import timedelta

            jd_total = satellite["satellite"].jdsatepoch + getattr(
                satellite["satellite"], "jdsatepochf", 0.0
            )

            epoch_dt = datetime(1970, 1, 1, tzinfo=timezone.utc) + timedelta(
                days=jd_total - 2440587.5
            )

            satellite["tle_epoch"] = epoch_dt.isoformat()
        except Exception:
            satellite["tle_epoch"] = None

        satellite["norad_id"] = norad_id
        satellites.append(satellite)

    return start_time, satellites


def safe_trajectory(satellite, start_time, horizon_hours, step_minutes):
    """
    Generate a trajectory, mapping SGP4
    propagation failures to HTTP 500.
    """

    try:
        return generate_trajectory(
            satellite["satellite"],
            start_time,
            hours=horizon_hours,
            step_minutes=step_minutes,
        )

    except RuntimeError as e:
        raise HTTPException(
            status_code=500,
            detail=f"SGP4 propagation failed for {satellite['name']}: {e!s}",
        )


def persist_forecast(db, start_time, request, satellites):

    try:
        for satellite in satellites:
            upsert_satellite(db, satellite["norad_id"], satellite["name"])

        record = ForecastRecord(
            start_time=start_time,
            horizon_hours=request.horizon_hours,
            step_minutes=request.step_minutes,
        )

        db.add(record)
        db.commit()
        db.refresh(record)

        return record.id

    except Exception as e:
        db.rollback()

        print(f"[DB] Failed to save forecast: {e}")

        return None


def persist_conjunction(db, forecast_id, result, satellite_a, satellite_b):

    try:
        record = ConjunctionRecord(
            forecast_id=forecast_id,
            satellite_a_norad_id=satellite_a["norad_id"],
            satellite_b_norad_id=satellite_b["norad_id"],
            tca=result["tca"],
            minimum_distance_km=result["minimum_distance_km"],
            coarse_tca=result.get("coarse_tca"),
            coarse_distance_km=(
                result["coarse_distance_km"]
                if result.get("coarse_distance_km") is not None
                else None
            ),
            risk_status=result["status"],
            refined=result.get("refined", True),
        )

        db.add(record)
        db.commit()
        db.refresh(record)

        return record.id

    except Exception as e:
        db.rollback()

        print(f"[DB] Failed to save conjunction: {e}")

        return None


# ==========================================
# HEALTH
# ==========================================


@app.get("/")
def root():

    return {
        "message": "Orbital Guardian API is running",
        "version": "2.0.0",
        "integrations": feature_flags(),
        "docs": "/docs",
    }


@app.get("/health")
def health(db: Session = Depends(get_db)):

    try:
        db.execute(text("SELECT 1"))

    except Exception:
        return {"status": "degraded", "database": "unavailable"}

    return {"status": "healthy", "integrations": feature_flags()}


# ==========================================
# LIVE OBJECT CATALOG (limited range)
# ==========================================
#
# In-memory cache so the frontend can browse
# tracked objects without hammering CelesTrak
# on every request.
# ==========================================

CATALOG_TTL_SECONDS = 6 * 3600

catalog_cache = {}


def get_catalog(group: str, limit: int, refresh: bool = False):

    now = time.time()

    cached = catalog_cache.get(group)

    if (
        not refresh
        and cached is not None
        and now - cached["fetched_at"] < CATALOG_TTL_SECONDS
    ):
        return cached["objects"][:limit]

    try:
        objects = fetch_catalog(group=group, limit=200)

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    except Exception as e:
        # Upstream failure — serve the last good
        # catalog if we have one, even if stale.
        if cached is not None:
            print(f"[CATALOG] Serving stale '{group}' catalog: {e!s}")
            return cached["objects"][:limit]

        raise HTTPException(
            status_code=502, detail=f"Catalog fetch failed for group '{group}': {e!s}"
        )

    catalog_cache[group] = {"fetched_at": now, "objects": objects}

    return objects[:limit]


@app.get("/catalog")
def catalog(
    group: str = Query("stations"),
    limit: int = Query(100, gt=0, le=200),
    refresh: bool = Query(False),
):
    """
    Live / near-live tracking list.

    Returns a limited range of orbital objects
    from CelesTrak with their current TLEs,
    cached server-side for 6 hours.
    """

    objects = get_catalog(group, limit, refresh)

    return {
        "group": group,
        "description": CATALOG_GROUPS.get(group),
        "count": len(objects),
        "objects": [
            {"norad_id": obj["norad_id"], "name": obj["name"]} for obj in objects
        ],
    }


# ==========================================
# FORECAST
# ==========================================


@app.post("/forecast")
def forecast(request: ForecastRequest, db: Session = Depends(get_db)):

    if len(request.objects) == 0:
        raise HTTPException(status_code=400, detail="At least one object is required.")

    # Remove duplicate NORAD IDs, preserve order
    norad_ids = list(dict.fromkeys(request.objects))

    start_time, satellites = load_satellites(norad_ids)

    # Generate trajectories (SGP4 — unchanged)
    trajectories = {}

    for satellite in satellites:
        trajectories[satellite["name"]] = safe_trajectory(
            satellite, start_time, request.horizon_hours, request.step_minutes
        )

    # Persist forecast metadata (trajectories stay dynamic)
    persist_forecast(db, start_time, request, satellites)

    # Convert trajectories to JSON (unchanged format)
    objects_output = []

    for satellite in satellites:
        name = satellite["name"]
        points = []

        for point in trajectories[name]:
            points.append(
                {
                    "time": point["time"].isoformat(),
                    "position": {
                        "x": point["position"][0],
                        "y": point["position"][1],
                        "z": point["position"][2],
                    },
                    "velocity": {
                        "x": point["velocity"][0],
                        "y": point["velocity"][1],
                        "z": point["velocity"][2],
                    },
                }
            )

        objects_output.append(
            {"norad_id": satellite["norad_id"], "name": name, "points": points}
        )

    return {
        "forecast": {
            "start_time": start_time.isoformat(),
            "horizon_hours": request.horizon_hours,
            "step_minutes": request.step_minutes,
            "total_points": len(trajectories[satellites[0]["name"]]),
        },
        "objects": objects_output,
    }


# ==========================================
# CONJUNCTION ANALYSIS
# ==========================================


@app.post("/conjunction")
def conjunction(request: ForecastRequest, db: Session = Depends(get_db)):

    # Need at least two satellites
    if len(request.objects) < 2:
        raise HTTPException(
            status_code=400, detail="At least two objects are required."
        )

    # Remove duplicate NORAD IDs, preserve order
    norad_ids = list(dict.fromkeys(request.objects))

    if len(norad_ids) < 2:
        raise HTTPException(
            status_code=400, detail="At least two distinct objects are required."
        )

    start_time, satellites = load_satellites(norad_ids)

    # Generate trajectories for ALL satellites
    trajectories = {}

    for satellite in satellites:
        trajectories[satellite["name"]] = safe_trajectory(
            satellite, start_time, request.horizon_hours, request.step_minutes
        )

    # Analyze every unique pair (A-B, A-C, B-C, ...)
    events = []

    for object_a, object_b in combinations(satellites, 2):
        result = find_closest_approach(
            trajectories[object_a["name"]],
            trajectories[object_b["name"]],
            object_a["satellite"],
            object_b["satellite"],
        )

        result["object_a"] = object_a
        result["object_b"] = object_b

        events.append(result)

    # Persist forecast once + every conjunction event
    forecast_id = persist_forecast(db, start_time, request, satellites)

    for event in events:
        persist_conjunction(
            db, forecast_id, event, event["object_a"], event["object_b"]
        )

    # Primary event = closest approach of all pairs.
    # Top-level response stays backward compatible
    # with the existing Cesium frontend.
    primary = min(events, key=lambda e: e["minimum_distance_km"])

    satellite_a = primary["object_a"]
    satellite_b = primary["object_b"]

    # Return existing response structure + all events
    return {
        "object_a": {"norad_id": satellite_a["norad_id"], "name": satellite_a["name"]},
        "object_b": {"norad_id": satellite_b["norad_id"], "name": satellite_b["name"]},
        "forecast": {
            "start_time": start_time.isoformat(),
            "horizon_hours": request.horizon_hours,
            "step_minutes": request.step_minutes,
            "trajectory_points": len(trajectories[satellite_a["name"]]),
        },
        "conjunction": {
            "tca": primary["tca"].isoformat(),
            "minimum_distance_km": primary["minimum_distance_km"],
            "coarse_tca": primary["coarse_tca"].isoformat(),
            "coarse_distance_km": primary["coarse_distance_km"],
            "status": primary["status"],
            "refined": primary["refined"],
        },
        "position_a": {
            "x": primary["position_a"][0],
            "y": primary["position_a"][1],
            "z": primary["position_a"][2],
        },
        "position_b": {
            "x": primary["position_b"][0],
            "y": primary["position_b"][1],
            "z": primary["position_b"][2],
        },
        # All pairwise events (new — additive)
        "events": [
            {
                "object_a": {
                    "norad_id": event["object_a"]["norad_id"],
                    "name": event["object_a"]["name"],
                },
                "object_b": {
                    "norad_id": event["object_b"]["norad_id"],
                    "name": event["object_b"]["name"],
                },
                "tca": event["tca"].isoformat(),
                "minimum_distance_km": event["minimum_distance_km"],
                "status": event["status"],
            }
            for event in sorted(events, key=lambda e: e["minimum_distance_km"])
        ],
    }


# ==========================================
# BATCH CONJUNCTION SCREENING
# ==========================================


@app.post("/screen")
def screen(request: ScreenRequest, db: Session = Depends(get_db)):
    """
    Screen all pairs of tracked objects for
    close approaches and rank every event by
    the explainable Operational Risk Priority.

    Delegates to the shared pipeline in
    backend.services.analysis_service — the exact same
    deterministic pipeline used by background analysis
    jobs. Response is backward compatible with v1 and
    adds confidence fields.
    """

    norad_ids = list(dict.fromkeys(request.objects))

    if len(norad_ids) < 2:
        raise HTTPException(
            status_code=400, detail="At least two distinct objects are required."
        )

    # Performance guard for the prototype:
    # all-pairs screening stays tractable.
    if len(norad_ids) > 50:
        raise HTTPException(
            status_code=400, detail="Maximum 50 objects per screening run."
        )

    try:
        result = run_screening_pipeline(
            norad_ids=norad_ids,
            horizon_hours=request.horizon_hours,
            step_minutes=request.step_minutes,
            screen_threshold_km=request.screen_threshold_km,
            top_n=request.top_n,
            reporter=ProgressReporter(),  # no-op sink: sync path
        )

    except ValueError as e:
        detail = str(e)

        status = 404 if "No TLE" in detail or "Unknown NORAD" in detail else 422

        raise HTTPException(status_code=status, detail=detail)

    return result


# ==========================================
# HISTORY ENDPOINTS
# ==========================================


@app.get("/forecasts")
def list_forecasts(
    limit: int = Query(20, gt=0, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):

    try:
        total = db.query(ForecastRecord).count()

        records = (
            db.query(ForecastRecord)
            .order_by(ForecastRecord.created_at.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )

    except Exception:
        raise HTTPException(
            status_code=503, detail="Database unavailable. History cannot be retrieved."
        )

    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "forecasts": [
            {
                "id": record.id,
                "start_time": record.start_time.isoformat(),
                "horizon_hours": record.horizon_hours,
                "step_minutes": record.step_minutes,
                "created_at": record.created_at.isoformat(),
            }
            for record in records
        ],
    }


@app.get("/conjunctions")
def list_conjunctions(
    limit: int = Query(20, gt=0, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):

    try:
        total = db.query(ConjunctionRecord).count()

        records = (
            db.query(ConjunctionRecord)
            .order_by(ConjunctionRecord.created_at.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )

    except Exception:
        raise HTTPException(
            status_code=503, detail="Database unavailable. History cannot be retrieved."
        )

    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "conjunctions": [
            {
                "id": record.id,
                "forecast_id": record.forecast_id,
                "satellite_a_norad_id": record.satellite_a_norad_id,
                "satellite_b_norad_id": record.satellite_b_norad_id,
                "tca": record.tca.isoformat(),
                "minimum_distance_km": record.minimum_distance_km,
                "coarse_tca": (
                    record.coarse_tca.isoformat() if record.coarse_tca else None
                ),
                "coarse_distance_km": record.coarse_distance_km,
                "risk_status": record.risk_status,
                "refined": record.refined,
                "created_at": record.created_at.isoformat(),
            }
            for record in records
        ],
    }
