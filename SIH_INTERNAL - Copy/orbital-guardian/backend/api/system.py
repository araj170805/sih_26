"""
System health and metrics — real probes only.
Services that are not configured report "NOT_CONFIGURED",
never a fabricated status.
"""

import time
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, text
from sqlalchemy.orm import Session

from backend.config import feature_flags
from backend.database.connection import SessionLocal, get_db
from backend.database.models import AnalysisJob

router = APIRouter(prefix="/system", tags=["system"])


@router.get("/health")
def system_health():
    services = []

    # ---------------------------------------------
    # Backend API (implicit — we're serving this)
    # ---------------------------------------------
    services.append({
        "service": "Backend API", "status": "ONLINE", "detail": None,
    })

    # ---------------------------------------------
    # Database (real connectivity + latency probe)
    # ---------------------------------------------
    db_status = {"service": "Database", "status": "OFFLINE",
                 "latency_ms": None}

    try:
        start = time.perf_counter()
        db = SessionLocal()
        try:
            db.execute(text("SELECT 1"))
            db_status["latency_ms"] = round(
                (time.perf_counter() - start) * 1000, 1
            )
            db_status["status"] = "ONLINE"
        finally:
            db.close()
    except Exception as e:
        db_status["detail"] = str(e)[:200]

    services.append(db_status)

    # ---------------------------------------------
    # Orbital data provider (real HEAD-style probe)
    # ---------------------------------------------
    provider = {
        "service": "Orbital Data Provider (CelesTrak)",
        "status": "UNKNOWN",
    }

    try:
        import requests

        response = requests.get(
            "https://celestrak.org/NORAD/elements/gp.php",
            params={"CATNR": 25544, "FORMAT": "TLE"},
            timeout=8,
        )

        provider["status"] = (
            "ONLINE" if response.status_code == 200 else "DEGRADED"
        )

    except Exception as e:
        provider["status"] = "DEGRADED"
        provider["detail"] = f"Probe failed: {str(e)[:150]}"

    services.append(provider)

    # ---------------------------------------------
    # TLE cache
    # ---------------------------------------------
    from backend.orbital.data_fetcher import CACHE_FILE

    cache_ok = False
    try:
        cache_ok = CACHE_FILE.exists() and CACHE_FILE.stat().st_size > 2
    except Exception:
        pass

    services.append({
        "service": "TLE Disk Cache",
        "status": "ONLINE" if cache_ok else "EMPTY",
        "detail": str(CACHE_FILE),
    })

    # ---------------------------------------------
    # SGP4 engine (real self-test propagation)
    # ---------------------------------------------
    sgp4_ok = False
    sgp4_error = None

    try:
        from sgp4.api import Satrec, jday

        sat = Satrec.twoline2rv(
            "1 25544U 98067A   24001.00000000  .00000000  00000-0  00000-0 0  9990",
            "2 25544  51.6400  10.0000 0005000  20.0000  30.0000 "
            "15.50000000123456",
        )

        jd, fr = jday(2024, 1, 1, 12, 0, 0)

        error, pos, vel = sat.sgp4(jd, fr)

        sgp4_ok = error == 0 and len(pos) == 3
    except Exception as e:
        sgp4_error = str(e)[:200]

    services.append({
        "service": "SGP4 Engine",
        "status": "ONLINE" if sgp4_ok else "OFFLINE",
        "detail": sgp4_error,
    })

    # ---------------------------------------------
    # Analysis job system
    # ---------------------------------------------
    jobs_online = False

    try:
        db = SessionLocal()

        try:
            active = (
                db.query(AnalysisJob)
                .filter(AnalysisJob.status.in_(["QUEUED", "RUNNING"]))
                .count()
            )

            queued = (
                db.query(AnalysisJob)
                .filter(AnalysisJob.status == "QUEUED")
                .count()
            )

            failed = (
                db.query(AnalysisJob)
                .filter(AnalysisJob.status == "FAILED")
                .count()
            )

            last_completed = (
                db.query(func.max(AnalysisJob.completed_at)).scalar()
            )

            jobs_online = True
        finally:
            db.close()

        services.append({
            "service": "Analysis Job System",
            "status": "ONLINE" if jobs_online else "OFFLINE",
            "metrics": {
                "active_jobs": active,
                "queued_jobs": queued,
                "failed_jobs_total": failed,
                "last_completed_analysis": (
                    last_completed.isoformat() if last_completed else None
                ),
            },
        })
    except Exception as e:
        services.append({
            "service": "Analysis Job System",
            "status": "OFFLINE",
            "detail": str(e)[:200],
        })

    # ---------------------------------------------
    # Optional integrations (honest states)
    # ---------------------------------------------

    flags = feature_flags()

    ai_state = "ONLINE" if flags["ai_copilot"] else "NOT_CONFIGURED"

    services.append({
        "service": f"AI Provider ({(flags.get('ai_provider') or 'gemini').title()} Copilot)",
        "status": ai_state,
        "detail": None if flags["ai_copilot"]
        else "Set GEMINI_API_KEY to enable LLM answers; deterministic "
             "explainer remains available.",
    })

    services.append({
        "service": "Vector Database (RAG)",
        "status": "ONLINE" if flags["vector_db"] else "LOCAL_FALLBACK",
        "detail": None if flags["vector_db"]
        else "Using built-in keyword retrieval over bundled corpus.",
    })

    services.append({
        "service": "Firebase Authentication",
        "status": "ONLINE" if flags["auth_mode"] == "firebase"
        else "NOT_CONFIGURED",
        "detail": None if flags["auth_mode"] == "firebase"
        else "Set FIREBASE_PROJECT_ID (and frontend VITE_FIREBASE_* vars) "
             "to enable Firebase sign-in; legacy local auth remains active.",
    })

    overall = "ONLINE"

    offline = [s for s in services if s["status"] == "OFFLINE"]

    degraded = [s for s in services if s["status"] in ("DEGRADED", "EMPTY")]

    if any(s["service"] == "Database" for s in offline):
        overall = "OFFLINE"
    elif offline or degraded:
        overall = "DEGRADED"

    return {
        "overall_status": overall,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "integrations": flags,
        "services": services,
    }


@router.get("/metrics")
def system_metrics(db: Session = Depends(get_db)):
    """Quick operational counters for the top bar / dashboard."""

    metrics = {}

    try:
        from backend.database.models import Conjunction, Forecast, Satellite

        metrics = {
            "satellites_cataloged": db.query(Satellite).count(),
            "forecasts_stored": db.query(Forecast).count(),
            "conjunctions_stored": db.query(Conjunction).count(),
        }

        jobs_active = (
            db.query(AnalysisJob)
            .filter(AnalysisJob.status.in_(["QUEUED", "RUNNING"]))
            .count()
        )

        metrics["active_jobs"] = jobs_active

    except Exception as e:
        return {"available": False, "detail": str(e)[:200]}

    return {"available": True, **metrics}
