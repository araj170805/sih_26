# ARCHITECTURE

## High-Level Overview

```
┌────────────────────────────  FRONTEND (Vite MPA)  ───────────────────────────┐
│  index.html (landing)   login/register.html   app.html (mission control)     │
│  CesiumJS globe · SSE pipeline panel · intelligence panels · timeline        │
└───────────────▲───────────────────────────────────────────┬──────────────────┘
                │ REST + Server-Sent Events                 │ JWT bearer
┌───────────────┴───────────────────────────────────────────▼──────────────────┐
│                            FASTAPI BACKEND                                   │
│                                                                              │
│  api/            auth · objects · analysis · conjunctions · watchlists       │
│                  notifications · analytics · system · ai · reports           │
│                                                                              │
│  jobs/           JobManager: background threads, live stage fan-out,         │
│                  DB-mirrored job/event history, notification triggers        │
│                                                                              │
│  services/       analysis_service — THE single deterministic pipeline        │
│                  auth_service — PBKDF2 + HS256 JWT (stdlib only)             │
│                                                                              │
│  orbital/        data_fetcher (CelesTrak + cache chain) · tle_parser         │
│                  propagator (SGP4) · trajectory · conjunction (TCA)          │
│                  risk (Operational Risk Priority)                            │
│                                                                              │
│  intelligence/   object_profile aggregator · curated registry                │
│                  confidence (deterministic freshness scoring)                │
│                                                                              │
│  rag/            retriever (offline keyword scoring over bundled corpus)     │
│                  copilot (grounded LLM w/ deterministic fallback)            │
│                                                                              │
│  database/       SQLAlchemy models + additive migrations                     │
└──────────────────────────────────────────────────────────────────────────────┘
                                │
                         PostgreSQL
```

## Design Principles

1. **Determinism at the core.** All positions, TCAs, distances,
   velocities and risk scores come from SGP4 + explicit formulas.
2. **AI is an explanation layer only.** The LLM receives verified system
   data as context and a strict prompt; without an API key the same facts
   are rendered by deterministic templates.
3. **One pipeline, two entry points.** `POST /screen` (sync) and
   `POST /analysis/start` (job + SSE) call the identical
   `run_screening_pipeline()`; progress callbacks are the only difference.
4. **Graceful degradation.** Every optional provider returns an explicit
   "not configured" state; nothing fabricates values.
5. **Additive evolution.** New columns arrive via idempotent migrations;
   v1 endpoints keep their response shapes.

## Analysis Pipeline Flow

```
POST /analysis/start
  └─ JobManager.submit()
       ├─ insert analysis_jobs row (QUEUED)
       ├─ background thread → run_screening_pipeline()
       │    FETCHING_ORBITAL_DATA   per-object TLE fetch (cache chain)
       │    VALIDATING_DATA         payload sanity checks
       │    PARSING_TLE             Satrec.twoline2rv (+ epoch capture)
       │    INITIALIZING_SGP4       models ready / failures skipped
       │    PROPAGATING_ORBITS      generate_trajectory() per object
       │    BROAD_PHASE_SCREENING   sampled min-distance per pair
       │    REFINING_CANDIDATES     find_closest_approach() ±60 s @1 s
       │    CALCULATING_TCA / MIN_SEP / REL_VEL   (inside refinement)
       │    CALCULATING_RISK        risk score + confidence
       │    SAVING_RESULTS          forecasts + conjunctions rows
       └─ every callback → SSE subscribers + analysis_job_events row
```

## Object Intelligence Data Flow

```
NORAD ID
  → object_profiles cache (6 h TTL)
  → fetch_tle() cache chain (memory → CelesTrak → fallback → stale)
  → SGP4: sub-satellite point, velocity, mean elements
    (inclination, apogee/perigee from semi-major axis & eccentricity)
  → identity/type (TLE naming + curated registry)
  → mission metadata (curated → optional provider → constellation hint
    → honest "unavailable"/debris context)
  → operational status (verified sources ONLY; never guessed)
  → conjunction context (real DB query)
  → unified profile + source list, cached
```

## Authentication Flow

- Register/login → PBKDF2 verification → access token (HS256 JWT,
  60 min) + opaque refresh token (SHA-256 hashed at rest, 7 days).
- Refresh rotates: used tokens are revoked.
- RBAC: `VIEWER < ANALYST < ADMIN` enforced by dependency factories;
  first registered account becomes ADMIN.

## RAG/AI Flow

```
question → context detection (selected object? event?)
  → tool retrieval: object profile API / event record / DB
  → knowledge retrieval: keyword-scored bundled corpus
  → context builder (VERIFIED SYSTEM DATA blocks)
  → [if configured] LLM with strict anti-hallucination prompt
  → else deterministic explainer templates
  → answer + source attribution
```

## Database Schema (v2.0)

| Table | Purpose |
|---|---|
| satellites | cataloged objects (unique norad_id) |
| forecasts | forecast runs |
| conjunctions | events incl. risk_score, rel. velocity, factors JSON, confidence |
| users | accounts, roles |
| refresh_tokens | hashed rotating refresh tokens |
| analysis_jobs | job status/counters/timings mirror |
| analysis_job_events | append-only progress history |
| watchlists / watchlist_objects | user object collections |
| notifications | in-app alerts (user or broadcast) |
| object_profiles | cached intelligence profiles + sources |
| reports | generated conjunction reports |

## Known Limitations

- Public TLE accuracy (~km at epoch, growing after) bounds all derived
  precision; the UI deliberately avoids centimeter-level claims.
- Operational Risk Priority is heuristic screening prioritization, not Pc.
- In-process job manager binds jobs to one worker (Redis prepared for scale-out).
