# API REFERENCE

Base URL (dev): `http://127.0.0.1:8000` · Interactive docs: `/docs`

Authentication: `Authorization: Bearer <access_token>`.
SSE endpoints also accept `?access_token=` (EventSource limitation).

Roles: **V** = any authenticated, **A** = ANALYST+, **D** = ADMIN.
Unmarked endpoints are public.

## Legacy v1 endpoints (unchanged behavior)

| Method | Path | Notes |
|---|---|---|
| GET | `/` | Service info + integration flags |
| GET | `/health` | DB-backed health |
| GET | `/catalog?group=&limit=&refresh=` | Live catalog, 6 h cache |
| POST | `/forecast` | SGP4 trajectories `{objects[], horizon_hours≤72, step_minutes≤60}` |
| POST | `/conjunction` | Pairwise closest approach (≥2 objects) |
| POST | `/screen` | Full deterministic screening pipeline (sync; same engine as jobs) |
| GET | `/forecasts` | History (paginated) |
| GET | `/conjunctions` | History (paginated) |

## Auth — `/auth`

| Method | Path | Role | Body / notes |
|---|---|---|---|
| POST | `/auth/register` | — | `{email, username, password}` → tokens. First user = ADMIN |
| POST | `/auth/login` | — | `{email, password}` → access+refresh tokens |
| POST | `/auth/refresh` | — | `{refresh_token}` → rotated tokens |
| POST | `/auth/logout` | V | revokes refresh token |
| GET | `/auth/me` | V | current profile |

## Objects — `/objects`

| Method | Path | Notes |
|---|---|---|
| GET | `/objects?group=visual&search=&limit=` | catalog browse/search |
| GET | `/objects/{norad_id}/profile` | unified intelligence profile (identity, mission, live orbit, data quality, conjunction context, sources) |
| GET | `/objects/{norad_id}/trajectory?hours=&step_minutes=` | single-object SGP4 trajectory |
| GET | `/objects/{norad_id}/conjunctions` | recorded events involving object |
| POST | `/objects/{norad_id}/refresh` | rebuild profile bypassing cache |

## Analysis Jobs — `/analysis`

| Method | Path | Role | Notes |
|---|---|---|---|
| POST | `/analysis/start` | A | `{objects[], horizon_hours?, step_minutes?, screen_threshold_km?, top_n?}` → `{job_ref}` |
| GET | `/analysis/{job_ref}` | — | state snapshot (live or DB history) |
| GET | `/analysis/{job_ref}/progress` | — | **SSE**: real stage/counter/timing events; heartbeats every ≤6 s |
| GET | `/analysis/jobs` | D | job monitoring |

SSE event types: `stage`, `progress`, `completed`, `failed`.
Counters include `objects_fetched`, `pairs_processed`, `candidates_found`,
`events_completed`; timings per stage in seconds.

## Conjunctions — `/conjunctions`

| Method | Path | Notes |
|---|---|---|
| GET | `/conjunctions/{event_id}` | full stored record |
| GET | `/conjunctions/{event_id}/risk` | Operational Risk Priority breakdown + deterministic explanation |
| GET | `/conjunctions/{event_id}/timeline?window_minutes=30&step_seconds=60` | real SGP4 replay steps around TCA |

## Watchlists — `/watchlists` (A)

| Method | Path |
|---|---|
| GET / POST | `/watchlists` |
| DELETE | `/watchlists/{id}` |
| POST | `/watchlists/{id}/objects` `{norad_id, name?}` |
| DELETE | `/watchlists/{id}/objects/{norad_id}` |
| GET | `/watchlists/{id}/conjunctions` |

## Notifications — `/notifications`

| Method | Path | Role |
|---|---|---|
| GET | `/notifications?unread_only=&limit=` | V (guests: broadcasts only) |
| POST | `/notifications/{id}/read` | V |
| POST | `/notifications/read-all` | V |

## Analytics — `/analytics`

| Method | Path | Notes |
|---|---|---|
| GET | `/analytics/summary?days=30` | real DB aggregates incl. risk distribution & type counts |
| GET | `/analytics/events-over-time?days=30` | daily series (`empty:true` when no data) |
| GET | `/analytics/analysis-duration` | actual job durations |

## System — `/system`

| Method | Path | Notes |
|---|---|---|
| GET | `/system/health` | per-service probes: DB latency, CelesTrak reachability, cache, SGP4 self-test, job counters, integration states |
| GET | `/system/metrics` | quick counters |

## AI — `/ai`

| Method | Path | Notes |
|---|---|---|
| POST | `/ai/chat` | `{question, norad_id?, conjunction_id?}` — grounded answer + sources; deterministic when no AI key |
| POST | `/ai/explain-event` | `{conjunction_id}` — explainable event narrative from real numbers |
| GET | `/ai/knowledge?query=` | direct RAG corpus retrieval |

## Reports — `/reports` (A to generate)

| Method | Path | Notes |
|---|---|---|
| POST | `/reports/conjunction/{event_id}` | generate + persist |
| GET | `/reports/{report_id}` | JSON content |
| GET | `/reports/{report_id}/html` | printable HTML |

## Error Model

Errors return `{"detail": "<human-readable>"}` with appropriate codes:
400 validation · 401 auth required/expired · 403 role/object ownership ·
404 unknown resource/NORAD · 409 conflict · 422 invalid TLE ·
502 upstream provider failure · 503 database/provider unavailable.
Internal stack traces and secrets are never exposed.
