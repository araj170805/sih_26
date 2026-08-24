# 🛰️ Orbital Guardian v2.0

**Space Traffic Intelligence & Conjunction Decision Support Platform**

> *See the encounter before it happens.*

Orbital Guardian fetches live orbital data for satellites and debris,
propagates their trajectories with the SGP4 standard, detects close
approaches with a two-phase screening pipeline, ranks every event with an
**explainable Operational Risk Priority**, enriches objects with mission
intelligence, streams the **real analysis pipeline live to the browser**,
and replays encounters in 3D — all in a dark aerospace mission-control
interface.

---

## ✨ What's New in v2.0

| Area | Upgrade |
|---|---|
| **Analysis jobs** | Background job system with **live SSE streaming** of actual pipeline stages (fetch → propagate → screen → refine → risk), counters and per-stage timings |
| **Object intelligence** | Click any NORAD ID: identity/type, verified mission context, live orbital state (lat/lon/alt/velocity/inclination/apogee/perigee/period), TLE freshness + data confidence, conjunction history |
| **Risk intelligence** | Explainable factor-by-factor risk bars, separated **data confidence**, honest "heuristic priority — NOT Pc" labeling |
| **Encounter replay** | Real SGP4 timeline from T−30 min to T+30 min around TCA on the Cesium globe |
| **Authentication** | JWT + rotating refresh tokens, PBKDF2 hashing, VIEWER/ANALYST/ADMIN roles |
| **Mission-control UI** | Landing page, login/register, dashboard with control panel / globe / intelligence panel / synced custom timeline |
| **Watchlists & notifications** | User object collections, in-app alert center (analysis results, high-priority events) |
| **Analytics & health** | Real DB-driven analytics; live system probes (DB latency, CelesTrak reachability, SGP4 self-test, job counters) |
| **AI Copilot** | Context-aware Q&A grounded strictly in system data + bundled scientific RAG knowledge base. Works without any AI key (deterministic mode) |
| **Reports** | Printable HTML conjunction reports with methodology, sources and disclaimers |

---

## Architecture at a Glance

```
Frontend (Vite MPA)          Backend (FastAPI)
├── index.html   landing    ├── api/          10 feature routers
├── login/register          ├── jobs/         background jobs + SSE
├── app.html     dashboard  ├── services/     THE deterministic pipeline
└── system.html  health     ├── orbital/      SGP4 · TCA · risk (unchanged core)
                              ├── intelligence/ profiles · confidence
                              ├── rag/          knowledge base + copilot
                              └── database/     SQLAlchemy models + migrations
```

Full details: [ARCHITECTURE.md](ARCHITECTURE.md) · Endpoints: [API.md](API.md)

## Tech Stack

- **Backend:** Python, FastAPI, SQLAlchemy, PostgreSQL, sgp4, requests
- **Auth:** stdlib PBKDF2 + HS256 JWT (no native deps)
- **Frontend:** Vanilla JS, CesiumJS, Vite (multi-page)
- **Testing:** pytest (offline-mocked pipeline tests included)

## Quick Start

```powershell
# 1. Database (PostgreSQL required)
createdb orbital_guardian

# 2. Environment
Copy-Item .env.example backend\.env   # set DATABASE_URL

# 3. Backend
cd backend
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install fastapi uvicorn sqlalchemy psycopg2-binary python-dotenv sgp4 requests httpx pytest
cd ..
python -m backend.database.init_db
uvicorn backend.api:app --reload --port 8000

# 4. Frontend (new terminal)
cd frontend\cesium-app
npm install
npm run dev
```

Open `http://localhost:5173` → landing page → **LAUNCH PLATFORM**.
Register the first account to become ADMIN.

Step-by-step guide incl. production notes: [SETUP.md](SETUP.md)

## The Deterministic Guarantee

- All positions, TCAs, miss distances, velocities come from **SGP4 only**.
- Risk scores are computed by a fixed weighted formula with published factors.
- Confidence is a pure function of TLE age.
- The AI layer **never invents** numbers — it receives verified data as
  context and falls back to deterministic explainers when unconfigured.
- Missing providers degrade to explicit `NOT_CONFIGURED` states. No fake
  "live" data is ever displayed.

## Scientific Disclaimers

- **Operational Risk Priority** is a screening/prioritization heuristic.
- It is **not** a Probability of Collision (**Pc**) — computing Pc requires
  covariance data that public TLEs do not contain.
- Public TLEs carry ~km-level uncertainty that grows after epoch; the UI
  deliberately avoids centimeter-level claims.

## Documentation Index

| Document | Contents |
|---|---|
| [SETUP.md](SETUP.md) | Full installation, DB init, migrations, testing, production |
| [ARCHITECTURE.md](ARCHITECTURE.md) | System design, data flows, schema |
| [API.md](API.md) | Every endpoint with roles and payloads |
| [EXTERNAL_SERVICES.md](EXTERNAL_SERVICES.md) | What credentials you can optionally provide, where they go, what breaks without them |

## License

Hackathon prototype built for Smart India Hackathon (SIH). Orbital data © CelesTrak.
