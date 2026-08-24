# SETUP GUIDE

## 1. Prerequisites

| Tool | Version |
|---|---|
| Python | 3.12+ |
| Node.js | 18+ |
| PostgreSQL | 14+ |

## 2–3. Install Python & Node

Install from python.org and nodejs.org (or use your OS package
manager). Verify:

```powershell
python --version
node --version
```

## 4–5. PostgreSQL setup + database creation

```sql
CREATE USER og_user WITH PASSWORD 'strong_password_here';
CREATE DATABASE orbital_guardian OWNER og_user;
```

## 6. Environment configuration

```powershell
Copy-Item .env.example backend\.env
# Edit backend\.env — set DATABASE_URL at minimum.
```

## 7. Backend installation

```powershell
cd backend
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install fastapi uvicorn sqlalchemy psycopg2-binary python-dotenv sgp4 requests httpx pytest
```

## 8. Frontend installation

```powershell
cd frontend\cesium-app
npm install
```

## 9–10. Database initialization & migrations

Run from the **project root** (`orbital-guardian/`):

```powershell
python -m backend.database.init_db
```

- Creates all missing tables.
- Applies idempotent additive column migrations (existing data is never
  touched). Safe to run repeatedly, including after upgrades.

## 11. Backend startup

From the project root:

```powershell
uvicorn backend.api:app --reload --port 8000
```

Interactive API docs: <http://127.0.0.1:8000/docs>

## 12. Frontend startup

```powershell
cd frontend\cesium-app
npm run dev
```

Open the printed URL (usually http://localhost:5173).

Pages:

| URL | Purpose |
|---|---|
| `/` | Landing page |
| `/register.html` | Create account (first account = ADMIN) |
| `/login.html` | Sign in |
| `/app.html` | Mission control dashboard |
| `/system.html` | System health (ADMIN) |

If the backend runs elsewhere, set the URL in the browser console:
`localStorage.setItem("og_api_url", "http://your-host:8000")`.

## 13. Job workers

Not required. Analysis jobs execute in-process via background threads
with SSE progress streaming. For multi-worker production deployments,
configure `REDIS_URL` (architecture prepared; see ARCHITECTURE.md).

## 14. RAG ingestion

Not required. The scientific knowledge base is bundled at
`backend/rag/knowledge_base/` and loaded automatically. Add `.md`
files there to extend it — retrieval picks them up on restart.

## 15. Testing

From the project root (PostgreSQL must be running):

```powershell
$env:PYTHONPATH="."
backend\.venv\Scripts\python.exe -m pytest backend/tests -v
```

## 16. Production considerations

- Set a strong `JWT_SECRET_KEY`.
- Set `FRONTEND_URL` to your origin to lock down CORS.
- Serve the built frontend (`npm run build` → `dist/`) behind any static
  host or reverse proxy; point the API at the same domain.
- Run PostgreSQL with regular backups.
- Use multiple uvicorn workers only after configuring Redis for jobs.
- Respect CelesTrak rate limits — keep cache TTLs ≥ 1 h.

---

See also: `README.md`, `ARCHITECTURE.md`, `API.md`, `EXTERNAL_SERVICES.md`
