"""
Analysis service — the shared conjunction-screening pipeline.

Extracted from backend/api.py's /screen endpoint so that both
the synchronous endpoint AND the background job runner execute
EXACTLY the same deterministic pipeline:

    fetch TLEs -> validate -> parse -> SGP4 propagate
    -> broad-phase screening -> candidate refinement
    -> relative velocity -> risk scoring

A `progress` callback receives real stage updates; nothing is
simulated. When progress is None (sync /screen path) the
pipeline behaves identically to the original implementation.
"""

import time
from datetime import datetime, timedelta, timezone
from itertools import combinations

from fastapi import HTTPException

from backend.database.connection import SessionLocal
from backend.database.models import Conjunction as ConjunctionRecord
from backend.database.models import Forecast as ForecastRecord
from backend.database.models import Satellite as SatelliteRecord
from backend.intelligence.confidence import compute_confidence
from backend.orbital.conjunction import calculate_distance, find_closest_approach
from backend.orbital.data_fetcher import fetch_tle
from backend.orbital.risk import compute_risk_score
from backend.orbital.tle_parser import parse_tle
from backend.orbital.trajectory import generate_trajectory

# Julian date -> UTC datetime.
# JD 2440587.5 = 1970-01-01 00:00 UTC.
_JD_UNIX_EPOCH_OFFSET = 2440587.5
_UNIX_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


def julian_to_datetime(jd: float, fr: float | None = None) -> datetime:
    if fr is None:
        fr = 0.0

    return _UNIX_EPOCH + timedelta(days=(jd + fr) - _JD_UNIX_EPOCH_OFFSET)


def satrec_epoch(satrec) -> datetime:
    """
    Version-tolerant Satrec epoch extraction.
    Newer sgp4 exposes jdsatepochf; older builds only jdsatepoch.
    """

    return julian_to_datetime(
        satrec.jdsatepoch, getattr(satrec, "jdsatepochf", 0.0)
    )


def upsert_satellite(db, norad_id: int, name: str):
    record = (
        db.query(SatelliteRecord).filter(SatelliteRecord.norad_id == norad_id).first()
    )

    if record is None:
        record = SatelliteRecord(norad_id=norad_id, name=name)
        db.add(record)
    elif record.name != name:
        record.name = name

    return record


def persist_forecast(db, start_time, horizon_hours, step_minutes, satellites):
    try:
        for satellite in satellites:
            upsert_satellite(db, satellite["norad_id"], satellite["name"])

        record = ForecastRecord(
            start_time=start_time,
            horizon_hours=horizon_hours,
            step_minutes=step_minutes,
        )

        db.add(record)
        db.commit()
        db.refresh(record)

        return record.id

    except Exception as e:
        db.rollback()
        print(f"[DB] Failed to save forecast: {e}")
        return None


def persist_conjunction(db, forecast_id, event):
    try:
        record = ConjunctionRecord(
            forecast_id=forecast_id,
            satellite_a_norad_id=event["object_a"]["norad_id"],
            satellite_b_norad_id=event["object_b"]["norad_id"],
            tca=event["tca"],
            minimum_distance_km=event["minimum_distance_km"],
            coarse_tca=event.get("coarse_tca"),
            coarse_distance_km=event.get("coarse_distance_km"),
            risk_status=event["status"],
            refined=event.get("refined", True),
            risk_score=event.get("risk_score"),
            relative_velocity_km_s=event.get("relative_velocity_km_s"),
            risk_factors=event.get("risk_factors"),
            confidence=event.get("confidence"),
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
# PIPELINE STAGES (public contract for UI)
# ==========================================

STAGES = [    "QUEUED",
    "FETCHING_ORBITAL_DATA",
    "VALIDATING_DATA",
    "PARSING_TLE",
    "INITIALIZING_SGP4",
    "PROPAGATING_ORBITS",
    "GENERATING_TRAJECTORIES",
    "BROAD_PHASE_SCREENING",
    "REFINING_CANDIDATES",
    "CALCULATING_TCA",
    "CALCULATING_MINIMUM_SEPARATION",
    "CALCULATING_RELATIVE_VELOCITY",
    "CALCULATING_RISK",
    "SAVING_RESULTS",
    "COMPLETED",
]


class ProgressReporter:
    """
    Collects real stage timings and forwards them to a sink.
    """

    def __init__(self, sink=None):
        self.sink = sink or (lambda **kwargs: None)
        self.stage_timings = {}
        self._stage_started = None
        self.counters = {}

    def begin_stage(self, stage, message=None, **counters):
        now = time.time()

        if self._stage_started is not None and self.current_stage:
            elapsed = now - self._stage_started
            self.stage_timings[self.current_stage] = round(elapsed, 2)

        self.current_stage = stage
        self._stage_started = now
        self.counters.update(counters)

        self.sink(
            type="stage",
            stage=stage,
            status="RUNNING",
            message=message,
            counters=dict(self.counters),
            timings=dict(self.stage_timings),
        )

    def update(self, message=None, **counters):
        self.counters.update(counters)

        self.sink(
            type="progress",
            stage=self.current_stage,
            status="RUNNING",
            message=message,
            counters=dict(self.counters),
            timings=dict(self.stage_timings),
        )

    def finish(self, result_summary=None):
        if self._stage_started is not None and self.current_stage:
            elapsed = time.time() - self._stage_started
            self.stage_timings[self.current_stage] = round(elapsed, 2)

        self.sink(
            type="completed",
            stage="COMPLETED",
            status="COMPLETED",
            counters=dict(self.counters),
            timings=dict(self.stage_timings),
            result=result_summary,
        )


def run_screening_pipeline(
    norad_ids: list[int],
    horizon_hours: float,
    step_minutes: int,
    screen_threshold_km: float,
    top_n: int,
    reporter: ProgressReporter | None = None,
    persist: bool = True,
) -> dict:
    """
    Execute the full deterministic screening pipeline.
    Returns the same response shape as POST /screen.
    """

    reporter = reporter or ProgressReporter()
    reporter.begin_stage("FETCHING_ORBITAL_DATA", f"0 / {len(norad_ids)} objects")

    # =========================================
    # 1-3. FETCH + VALIDATE + PARSE
    # =========================================

    start_time = datetime.now(timezone.utc)
    satellites = []
    fetch_errors = {}

    for index, norad_id in enumerate(norad_ids):
        try:
            tle = fetch_tle(norad_id)

            if not tle or "line1" not in tle:
                raise ValueError("Empty or malformed TLE payload")

            satellite = parse_tle(tle["name"], tle["line1"], tle["line2"])

            satellite["norad_id"] = norad_id
            satellite["tle_epoch"] = satrec_epoch(
                satellite["satellite"]
            ).isoformat()
            satellite["source"] = tle.get("source", "celestrak")

            satellites.append(satellite)

        except ValueError as e:
            fetch_errors[norad_id] = f"Unknown NORAD ID or invalid TLE: {e}"

        except Exception as e:
            fetch_errors[norad_id] = str(e)

        reporter.update(
            f"{index + 1} / {len(norad_ids)} objects completed",
            objects_fetched=index + 1,
            progress_percentage=(index + 1) / len(norad_ids) * 30,
        )

    valid_satellites = [s for s in satellites]

    if len(valid_satellites) < 2:
        detail = "; ".join(f"NORAD {k}: {v}" for k, v in fetch_errors.items())
        raise ValueError(f"Need at least two analyzable objects. {detail}")

    # =========================================
    # 4. SGP4 INITIALIZED (parse succeeded)
    # =========================================

    reporter.begin_stage(
        "INITIALIZING_SGP4",
        f"{len(valid_satellites)} SGP4 models initialized "
        f"({len(fetch_errors)} skipped)",
        objects_total=len(norad_ids),
        objects_valid=len(valid_satellites),
    )

    pairs_total = len(valid_satellites) * (len(valid_satellites) - 1) // 2

    # =========================================
    # 5-6. PROPAGATE TRAJECTORIES
    # =========================================

    reporter.begin_stage(
        "PROPAGATING_ORBITS", f"0 / {len(valid_satellites)} objects"
    )

    valid = []
    failed_propagation = []

    for index, satellite in enumerate(valid_satellites):
        try:
            trajectory = generate_trajectory(
                satellite["satellite"],
                start_time,
                hours=horizon_hours,
                step_minutes=step_minutes,
            )
        except RuntimeError as e:
            print(f"[SCREEN] Skipping {satellite['name']}: {e}")
            failed_propagation.append(satellite["norad_id"])
            continue

        satellite["trajectory"] = trajectory
        valid.append(satellite)

        reporter.update(
            f"{index + 1} / {len(valid_satellites)} objects propagated",
            objects_propagated=index + 1,
            progress_percentage=30 + (index + 1) / len(valid_satellites) * 25,
        )

    # =========================================
    # 7. BROAD-PHASE SCREENING
    # =========================================

    reporter.begin_stage(
        "BROAD_PHASE_SCREENING", f"0 / {pairs_total} pairs", pairs_total=pairs_total
    )

    events = []
    candidates = []
    screened_pairs = 0

    for object_a, object_b in combinations(valid, 2):
        sampled_min = min(
            calculate_distance(point_a["position"], point_b["position"])
            for point_a, point_b in zip(
                object_a["trajectory"], object_b["trajectory"]
            )
        )

        screened_pairs += 1

        reporter.update(
            f"{screened_pairs} / {pairs_total} pairs screened",
            pairs_processed=screened_pairs,
            candidates_found=len(candidates),
            progress_percentage=55 + screened_pairs / max(pairs_total, 1) * 20,
        )

        if sampled_min > screen_threshold_km:
            continue

        candidates.append((object_a, object_b))

    # =========================================
    # 8-12. REFINEMENT + TCA + RISK
    # =========================================

    total_candidates = len(candidates)

    reporter.begin_stage(
        "REFINING_CANDIDATES",
        f"0 / {total_candidates} candidates",
        candidates_found=total_candidates,
    )

    for index, (object_a, object_b) in enumerate(candidates):
        result = find_closest_approach(
            object_a["trajectory"],
            object_b["trajectory"],
            object_a["satellite"],
            object_b["satellite"],
        )

        reporter.update(
            f"Refining {index + 1} / {total_candidates}",
            events_completed=index + 1,
            progress_percentage=75 + (index + 1) / max(total_candidates, 1) * 15,
        )

        hours_to_tca = (result["tca"] - start_time).total_seconds() / 3600.0

        score, level, factors = compute_risk_score(
            result["minimum_distance_km"],
            result["relative_velocity_km_s"],
            hours_to_tca,
            object_names=[object_a["name"], object_b["name"]],
        )

        # Deterministic data-confidence assessment.
        confidence, confidence_detail = compute_confidence(
            object_a.get("tle_epoch"), object_b.get("tle_epoch"), start_time
        )

        result["object_a"] = {"norad_id": object_a["norad_id"], "name": object_a["name"]}
        result["object_b"] = {"norad_id": object_b["norad_id"], "name": object_b["name"]}
        result["risk_score"] = score
        result["risk_level"] = level
        result["risk_factors"] = factors
        result["confidence"] = confidence
        result["confidence_detail"] = confidence_detail
        result["hours_to_tca"] = round(hours_to_tca, 3)

        events.append(result)

    # =========================================
    # 13. RANK + PERSIST
    # =========================================

    reporter.begin_stage("SAVING_RESULTS")

    events.sort(key=lambda e: (-e["risk_score"], e["minimum_distance_km"]))

    top_events = events[:top_n]

    forecast_id = None

    if persist:
        try:
            db = SessionLocal()

            try:
                forecast_id = persist_forecast(
                    db, start_time, horizon_hours, step_minutes, valid
                )

                persisted = [
                    event_id
                    for event_id in (
                        persist_conjunction(db, forecast_id, event)
                        for event in top_events
                    )
                    if event_id
                ]

                # Attach generated IDs so clients can open
                # event detail pages immediately.
                for event_id, event in zip(persisted, top_events):
                    event["conjunction_id"] = event_id

            finally:
                db.close()

        except Exception as e:
            print(f"[DB] Persistence error: {e}")

    summary = {
        "start_time": start_time.isoformat(),
        "horizon_hours": horizon_hours,
        "step_minutes": step_minutes,
        "objects_screened": len(valid),
        "fetch_errors": {str(k): v for k, v in fetch_errors.items()},
        "propagation_failures": failed_propagation,
        "pairs_screened": screened_pairs,
        "pairs_flagged": len(events),
        "screen_threshold_km": screen_threshold_km,
        "forecast_id": forecast_id,
    }

    reporter.finish(result_summary=summary)

    return {
        "screening": summary,
        "alerts": [            {
                "conjunction_id": event.get("conjunction_id"),
                "object_a": event["object_a"],
                "object_b": event["object_b"],
                "tca": event["tca"].isoformat(),
                "hours_to_tca": event["hours_to_tca"],
                "minimum_distance_km": round(event["minimum_distance_km"], 4),
                "coarse_distance_km": round(event["coarse_distance_km"], 4),
                "relative_velocity_km_s": round(event["relative_velocity_km_s"], 3),
                "risk_score": event["risk_score"],
                "risk_level": event["risk_level"],
                "risk_factors": event["risk_factors"],
                "confidence": event["confidence"],
                "confidence_detail": event["confidence_detail"],
                "status": event["status"],
                "position_a": {
                    "x": event["position_a"][0],
                    "y": event["position_a"][1],
                    "z": event["position_a"][2],
                },
                "position_b": {
                    "x": event["position_b"][0],
                    "y": event["position_b"][1],
                    "z": event["position_b"][2],
                },
            }
            for event in top_events
        ],
    }
