# EXTERNAL SERVICES — WHAT YOU NEED TO PROVIDE

Orbital Guardian is designed so the **core platform works with zero
external credentials**: live TLE data comes from CelesTrak (public,
keyless), propagation is local SGP4, and the AI Copilot falls back to a
deterministic grounded explainer.

Everything below is **optional** unless marked otherwise. When an
integration is not configured, the related feature is disabled or
degrades gracefully and the UI shows `Configuration Required` /
`NOT_CONFIGURED`. The system never fakes data from a missing provider.

---

## 1. PostgreSQL — REQUIRED

| | |
|---|---|
| USED FOR | All persistence: users, jobs, forecasts, conjunctions, watchlists, notifications |
| REQUIRED | **Yes** |
| YOU NEED TO PROVIDE | A local or hosted PostgreSQL 14+ instance |
| PLACE IT HERE | `DATABASE_URL=postgresql://user:password@localhost:5432/orbital_guardian` (in `backend/.env`) |
| HOW TO TEST | `python -m backend.database.init_db` → prints table list |
| IF NOT CONFIGURED | Backend fails to start (by design — no silent data loss) |

---

## 2. CelesTrak — REQUIRED (but keyless)

| | |
|---|---|
| USED FOR | Live TLE orbital data by NORAD ID and catalog groups |
| REQUIRED | Yes (the only source of real orbital elements) |
| YOU NEED TO PROVIDE | Nothing — public API, no key |
| ENV VARIABLES | `CELESTRAK_BASE_URL`, `CELESTRAK_CACHE_TTL_SECONDS` |
| HOW TO TEST | `curl "https://celestrak.org/NORAD/elements/gp.php?CATNR=25544&FORMAT=TLE"` |
| IF UNAVAILABLE | Automatic fallback provider + stale-cache serving; `/system/health` shows DEGRADED |

> Be polite to CelesTrak: the built-in cache TTLs exist so repeated
> analyses don't hammer it. Don't set `CELESTRAK_CACHE_TTL_SECONDS`
> below ~3600.

---

## 3. Google Gemini — OPTIONAL (AI Copilot + RAG)

| | |
|---|---|
| SERVICE | Google Gemini (Generative Language API) |
| USED FOR | AI Space Intelligence Copilot answers and event explanations; embeddings for RAG retrieval |
| REQUIRED | No |
| HOW TO GET IT | Free key at https://aistudio.google.com/apikey |
| WHAT CREDENTIAL | `GEMINI_API_KEY` |
| PLACE IT HERE | `backend/.env` → `GEMINI_API_KEY=AIza...` (+ `AI_PROVIDER=gemini`) |
| HOW TO TEST | `GET /system/health` → "AI Provider" ONLINE; or POST `/ai/chat` and check `mode` |
| FALLBACK | Deterministic grounded explainer + bundled knowledge base ("deterministic mode"). Core analysis unaffected. |

---

## 3b. Firebase Authentication

| | |
|---|---|
| SERVICE | Firebase Authentication (email/password) |
| USED FOR | All user sign-in/registration |
| REQUIRED | Optional — legacy local JWT auth remains active as fallback |
| SETUP | 1) console.firebase.google.com → create project 2) Authentication → Sign-in method → enable Email/Password 3) Project settings → General → copy **Project ID** and web-app config |
| BACKEND ENV | `FIREBASE_PROJECT_ID=your-project-id` (in `backend/.env`) |
| FRONTEND ENV | `frontend/cesium-app/.env`: `VITE_FIREBASE_API_KEY`, `VITE_FIREBASE_AUTH_DOMAIN`, `VITE_FIREBASE_PROJECT_ID`, `VITE_FIREBASE_APP_ID` |
| HOW TO TEST | Register via `/register.html`; `/system/health` shows "Firebase Authentication: ONLINE" |
| FALLBACK | Without config, backend keeps issuing its own JWTs and pages show a clear configuration message |

---

## 4. Embeddings Provider — OPTIONAL (future RAG upgrade)

| | |
|---|---|
| USED FOR | Vector embeddings for semantic retrieval over the knowledge base |
| REQUIRED | No |
| ENV VARIABLES | `EMBEDDING_PROVIDER`, `EMBEDDING_API_KEY`, `EMBEDDING_MODEL` |
| FALLBACK | Built-in deterministic keyword retrieval over the bundled corpus (already active) |

**What will not work without it:** nothing today; semantic search is a
future enhancement. The retriever interface is ready for it.

---

## 5. Vector Database — OPTIONAL

| | |
|---|---|
| USED FOR | Storing/retrieving knowledge-base embeddings at scale |
| REQUIRED | No |
| ENV VARIABLES | `VECTOR_DB_PROVIDER`, `VECTOR_DB_URL`, `VECTOR_DB_API_KEY` |
| FALLBACK | Local in-process retrieval (no server needed) |

---

## 6. Catalog Metadata Provider — OPTIONAL

| | |
|---|---|
| SERVICE EXAMPLE | SatNOGS DB (`https://db.satnogs.org/api/`) |
| USED FOR | Enriched object catalog metadata (alternate names, countries, launch dates) |
| REQUIRED | No |
| ENV VARIABLES | `CATALOG_PROVIDER`, `CATALOG_API_BASE_URL`, `CATALOG_API_KEY` |
| FALLBACK | TLE-derived identity + curated local registry (ISS, HST, NOAA 18, Tianhe) |

---

## 7. Mission Metadata Provider — OPTIONAL

| | |
|---|---|
| USED FOR | Verified mission/operator/launch metadata for arbitrary objects |
| REQUIRED | No |
| ENV VARIABLES | `MISSION_METADATA_PROVIDER`, `MISSION_METADATA_API_BASE_URL`, `MISSION_METADATA_API_KEY` |
| FALLBACK | Curated registry for famous objects; honest "No verified mission metadata available" otherwise. Debris never gets fake missions. |

---

## 8. Redis — OPTIONAL (future)

| | |
|---|---|
| USED FOR | Multi-worker job queue / shared cache |
| REQUIRED | No — current job manager runs in-process per backend worker |
| ENV VARIABLE | `REDIS_URL` |
| LIMITATION WITHOUT IT | Analysis jobs must be consumed on the same uvicorn worker that started them (fine for single-worker deployments) |

---

## 9. SMTP (Email notifications) — OPTIONAL

| | |
|---|---|
| USED FOR | Email delivery of alerts (in-app notifications need nothing) |
| REQUIRED | No |
| ENV VARIABLES | `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_FROM` |
| FALLBACK | In-app notification center always works |

---

## SECURITY RULES ALREADY ENFORCED IN CODE

- Secrets only ever come from environment variables (`backend/.env`,
  gitignored).
- `.env.example` contains placeholders only.
- Missing keys disable features — they are never logged or embedded in
  responses.
