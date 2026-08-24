"""
In-process analysis job manager.

Runs the screening pipeline on background threads and
tracks real progress. Job state is mirrored to the
database (analysis_jobs / analysis_job_events) so history
and monitoring survive restarts.

SSE subscribers attach per job_id; every progress callback
is broadcast to them. No progress is ever simulated.
"""

import queue
import threading
import uuid
from datetime import datetime, timezone

from backend.database.connection import SessionLocal
from backend.database.models import AnalysisJob as AnalysisJobRecord
from backend.database.models import AnalysisJobEvent, JobStatus, Notification
from backend.services.analysis_service import ProgressReporter, run_screening_pipeline


def _now_utc():
    return datetime.now(timezone.utc)


class JobHandle:
    """Runtime state for one analysis job + SSE fan-out."""

    def __init__(self, job_ref: str):
        self.job_ref = job_ref

        self.status = JobStatus.QUEUED.value
        self.stage = "QUEUED"
        self.message = None
        self.counters = {}
        self.timings = {}
        self.progress_percentage = 0.0
        self.result = None
        self.error = None

        self.subscribers: list[queue.Queue] = []
        self.lock = threading.Lock()

    def snapshot(self) -> dict:
        with self.lock:
            return {
                "job_ref": self.job_ref,
                "status": self.status,
                "stage": self.stage,
                "message": self.message,
                "progress_percentage": round(self.progress_percentage, 1),
                "counters": dict(self.counters),
                "timings": dict(self.timings),
                "result": self.result,
                "error": self.error,
            }

    def _publish(self, event: dict):
        with self.lock:
            dead = []

            for q in self.subscribers:
                try:
                    q.put_nowait(event)
                except Exception:
                    dead.append(q)

            for q in dead:
                self.subscribers.remove(q)

    def subscribe(self) -> queue.Queue:
        q = queue.Queue(maxsize=1000)

        with self.lock:
            # Replay current state so late subscribers catch up.
            q.put({"type": "state", **self.snapshot()})
            self.subscribers.append(q)

        return q

    def unsubscribe(self, q: queue.Queue):
        with self.lock:
            if q in self.subscribers:
                self.subscribers.remove(q)


class JobManager:
    def __init__(self):
        self._jobs: dict[str, JobHandle] = {}
        self._lock = threading.Lock()

    def get(self, job_ref: str) -> JobHandle | None:
        return self._jobs.get(job_ref)

    def submit(
        self,
        norad_ids: list[int],
        horizon_hours: float,
        step_minutes: int,
        screen_threshold_km: float,
        top_n: int,
        user_id: int | None = None,
    ) -> JobHandle:
        job_ref = f"OG-J-{uuid.uuid4().hex[:10]}"

        handle = JobHandle(job_ref)

        with self._lock:
            self._jobs[job_ref] = handle

        self._persist_job_record(handle, norad_ids, horizon_hours, step_minutes, user_id)

        thread = threading.Thread(
            target=self._run,
            args=(handle, norad_ids, horizon_hours, step_minutes,
                  screen_threshold_km, top_n),
            daemon=True,
            name=f"analysis-{job_ref}",
        )

        thread.start()

        return handle

    # ---------------------------------------------
    # DB MIRRORING
    # ---------------------------------------------

    def _persist_job_record(self, handle, norad_ids, horizon_hours, step_minutes,
                            user_id):
        try:
            db = SessionLocal()

            try:
                pairs_total = max(len(norad_ids), 0)
                record = AnalysisJobRecord(
                    job_ref=handle.job_ref,
                    user_id=user_id,
                    status=JobStatus.QUEUED.value,
                    current_stage="QUEUED",
                    object_count=len(norad_ids),
                    pairs_total=pairs_total * (pairs_total - 1) // 2,
                    request_payload={
                        "objects": list(norad_ids),
                        "horizon_hours": horizon_hours,
                        "step_minutes": step_minutes,
                    },
                )

                db.add(record)
                db.commit()
            finally:
                db.close()

        except Exception as e:
            print(f"[JOBS] Could not persist job record: {e}")

    def _record_event(self, job_ref, snapshot):
        try:
            db = SessionLocal()

            try:
                record = (
                    db.query(AnalysisJobRecord)
                    .filter(AnalysisJobRecord.job_ref == job_ref)
                    .first()
                )

                if record is None:
                    return

                record.status = snapshot["status"]
                record.current_stage = snapshot["stage"]
                record.progress_percentage = snapshot["progress_percentage"]

                if snapshot["counters"]:
                    c = snapshot["counters"]
                    if "pairs_total" in c:
                        record.pairs_total = c["pairs_total"]
                    if "pairs_processed" in c:
                        record.pairs_processed = c["pairs_processed"]
                    if "candidates_found" in c:
                        record.candidates_found = c["candidates_found"]
                    if "events_completed" in c:
                        record.events_completed = c["events_completed"]

                if snapshot["result"]:
                    record.result_summary = snapshot["result"]

                if snapshot["status"] == JobStatus.COMPLETED.value or snapshot[
                    "error"
                ]:
                    record.completed_at = _now_utc()

                if snapshot["error"]:
                    record.error_message = str(snapshot["error"])[:2000]

                if (
                    snapshot["status"] == JobStatus.RUNNING.value
                    and not record.started_at
                ):
                    record.started_at = _now_utc()

                db.add(
                    AnalysisJobEvent(
                        job_id=record.id,
                        stage=snapshot["stage"],
                        message=snapshot["message"],
                        progress_percentage=snapshot["progress_percentage"],
                        payload={"counters": snapshot["counters"]},
                    )
                )

                db.commit()

            finally:
                db.close()

        except Exception as e:
            print(f"[JOBS] Could not persist job event: {e}")

    def _notify(self, handle, title, body, category, link=None):
        try:
            db = SessionLocal()

            try:
                record = (
                    db.query(AnalysisJobRecord)
                    .filter(AnalysisJobRecord.job_ref == handle.job_ref)
                    .first()
                )

                db.add(
                    Notification(
                        user_id=record.user_id if record else None,
                        category=category,
                        title=title,
                        body=body[:500] if body else None,
                        link=link,
                    )
                )

                db.commit()
            finally:
                db.close()

        except Exception as e:
            print(f"[JOBS] Could not create notification: {e}")

    # ---------------------------------------------
    # EXECUTION
    # ---------------------------------------------

    def _run(self, handle, norad_ids, horizon_hours, step_minutes,
             screen_threshold_km, top_n):
        import time as _time

        started = _time.time()

        # Throttle DB persistence: stage transitions always persist;
        # intermediate progress events persist only every >=5% gain
        # (SSE subscribers still get every tick).
        last_persisted_progress = {"value": -100.0}

        def should_persist(event):
            etype = event.get("type")

            if etype in ("stage", "completed", "failed"):
                return True

            progress = float(handle.progress_percentage or 0)

            if progress - last_persisted_progress["value"] >= 5:
                last_persisted_progress["value"] = progress
                return True

            return False

        def sink(**event):
            with handle.lock:
                etype = event.get("type")

                if etype in ("stage", "progress", "completed"):
                    handle.stage = event.get("stage", handle.stage)
                    handle.message = event.get("message")
                    handle.counters = event.get("counters", handle.counters)
                    handle.timings = event.get("timings", handle.timings)

                    if etype == "completed":
                        handle.status = JobStatus.COMPLETED.value
                        handle.progress_percentage = 100.0
                        handle.result = event.get("result")

                elif etype == "failed":
                    handle.status = JobStatus.FAILED.value
                    handle.error = event.get("error")
                    handle.progress_percentage = 100.0

            handle._publish({"job_ref": handle.job_ref, **event})

            if should_persist(event):
                self._record_event(handle.job_ref, handle.snapshot())

        reporter = ProgressReporter(sink=sink)

        with handle.lock:
            handle.status = JobStatus.RUNNING.value

        handle._publish({
            "type": "stage",
            "stage": "FETCHING_ORBITAL_DATA",
            "status": "RUNNING",
            "message": f"0 / {len(norad_ids)} objects",
        })

        try:
            result = run_screening_pipeline(
                norad_ids=norad_ids,
                horizon_hours=horizon_hours,
                step_minutes=step_minutes,
                screen_threshold_km=screen_threshold_km,
                top_n=top_n,
                reporter=reporter,
            )

            duration = round(_time.time() - started, 2)

            alerts = result.get("alerts", [])

            highest = max(
                (a["risk_score"] for a in alerts), default=0
            )

            if alerts and highest >= 60:
                top = alerts[0]

                self._notify(
                    handle,
                    f"High-priority conjunction detected ({top['risk_level']})",
                    f"{top['object_a']['name']} × {top['object_b']['name']} — "
                    f"{top['minimum_distance_km']:.1f} km at TCA. "
                    f"{len(alerts)} events found.",
                    "high_priority_event",
                )
            else:
                self._notify(
                    handle,
                    "Analysis completed",
                    f"{result['screening']['objects_screened']} objects screened, "
                    f"{len(alerts)} flagged events.",
                    "analysis_completed",
                )

            sink(
                type="completed",
                stage="COMPLETED",
                status="COMPLETED",
                counters={**reporter.counters, "duration_seconds": duration},
                timings=reporter.stage_timings,
                result=result["screening"],
            )

        except Exception as e:
            handle.error = str(e)

            with handle.lock:
                handle.status = JobStatus.FAILED.value

            handle._publish({
                "type": "failed",
                "stage": handle.stage,
                "status": "FAILED",
                "error": str(e),
            })

            self._notify(
                handle,
                "Analysis failed",
                str(e)[:300],
                "analysis_failed",
            )


manager = JobManager()
