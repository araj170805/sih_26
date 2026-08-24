"""
Central application configuration.

Every external integration reads its credentials from
environment variables (backend/.env). Missing optional
credentials disable the related feature gracefully â€”
the platform never crashes because a provider key is absent.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent          # backend/
BACKEND_DIR = BASE_DIR.parent                        # project root

load_dotenv(BASE_DIR / ".env")                       # backend/.env


def _get(key, default=None):
    """
    Read an env var; values that are empty or still contain the
    '<<< FILL ME' placeholder count as NOT configured so optional
    integrations degrade gracefully instead of failing at call time.
    """

    value = os.getenv(key)

    if value is None:
        return default

    value = value.strip()

    if not value or "FILL ME" in value or value.startswith("<"):
        return default

    return value


def _get_int(key, default):
    try:
        return int(os.getenv(key, str(default)))
    except (TypeError, ValueError):
        return default


# ==========================================
# APPLICATION
# ==========================================

APP_ENV = _get("APP_ENV", "development")
APP_NAME = _get("APP_NAME", "Orbital Guardian")
FRONTEND_URL = _get("FRONTEND_URL", "*")

# ==========================================
# AUTHENTICATION
# ==========================================
#
# JWT_SECRET_KEY MUST be overridden in production.
# The development fallback keeps local setup frictionless.

JWT_SECRET_KEY = _get("JWT_SECRET_KEY", "dev-only-insecure-secret-change-me")
JWT_ALGORITHM = _get("JWT_ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = _get_int("ACCESS_TOKEN_EXPIRE_MINUTES", 60)
REFRESH_TOKEN_EXPIRE_DAYS = _get_int("REFRESH_TOKEN_EXPIRE_DAYS", 7)

# PBKDF2 parameters (stdlib password hashing).
PBKDF2_ITERATIONS = _get_int("PBKDF2_ITERATIONS", 260_000)

# ==========================================
# ORBITAL DATA
# ==========================================

CELESTRAK_BASE_URL = _get(
    "CELESTRAK_BASE_URL",
    "https://celestrak.org/NORAD/elements/gp.php",
)
CELESTRAK_CACHE_TTL_SECONDS = _get_int("CELESTRAK_CACHE_TTL_SECONDS", 4 * 3600)

# ==========================================
# OPTIONAL CATALOG / MISSION METADATA PROVIDERS
# ==========================================
#
# When unconfigured, object intelligence falls back to
# TLE-derived data + the curated local registry.

CATALOG_PROVIDER = _get("CATALOG_PROVIDER")  # e.g. "satnogs"
CATALOG_API_BASE_URL = _get("CATALOG_API_BASE_URL")
CATALOG_API_KEY = _get("CATALOG_API_KEY")

MISSION_METADATA_PROVIDER = _get("MISSION_METADATA_PROVIDER")
MISSION_METADATA_API_BASE_URL = _get("MISSION_METADATA_API_BASE_URL")
MISSION_METADATA_API_KEY = _get("MISSION_METADATA_API_KEY")

# ==========================================
# FIREBASE AUTHENTICATION
# ==========================================
#
# The frontend signs users in with Firebase; the backend verifies
# each ID token against Google's public keys. Only the project ID
# is needed here â€” no service account.

FIREBASE_PROJECT_ID = _get("FIREBASE_PROJECT_ID")

firebase_configured = bool(FIREBASE_PROJECT_ID)

# ==========================================
# AI PROVIDER â€” Gemini / OpenAI-compatible
# ==========================================
#
# AI_PROVIDER selects the backend: "gemini" or "openai".
# Gemini key: https://aistudio.google.com/apikey

AI_PROVIDER = _get("AI_PROVIDER", "gemini" if _get("GEMINI_API_KEY") else None)
AI_API_KEY = _get("GEMINI_API_KEY") or _get("AI_API_KEY")
AI_MODEL = _get("AI_MODEL", "gemini-3.6-flash")
AI_BASE_URL = _get(
    "AI_BASE_URL",
    "https://generativelanguage.googleapis.com/v1beta"
    if (AI_PROVIDER == "gemini" or _get("GEMINI_API_KEY"))
    else "https://api.openai.com/v1",
)

ai_provider_kind = (
    "gemini" if ("gemini" in (AI_PROVIDER or "") or "generativelanguage" in AI_BASE_URL) else "openai"
)

ai_configured = bool(AI_API_KEY)

# ==========================================
# EMBEDDINGS / VECTOR DATABASE (RAG)
# ==========================================
#
# Optional. Without them, retrieval uses lightweight
# in-process keyword scoring over the bundled corpus.

EMBEDDING_PROVIDER = _get("EMBEDDING_PROVIDER", "gemini" if ai_provider_kind == "gemini" else None)
EMBEDDING_API_KEY = _get("GEMINI_API_KEY") or _get("EMBEDDING_API_KEY")
EMBEDDING_MODEL = _get("EMBEDDING_MODEL", "text-embedding-004")

embeddings_configured = bool(EMBEDDING_PROVIDER and EMBEDDING_API_KEY)

VECTOR_DB_PROVIDER = _get("VECTOR_DB_PROVIDER", "pgvector" if embeddings_configured else None)
VECTOR_DB_URL = _get("VECTOR_DB_URL")

# ==========================================
# CACHE / JOB QUEUE
# ==========================================
#
# Reserved. The current job manager runs in-process;
# Redis enables multi-worker deployments later.

REDIS_URL = _get("REDIS_URL")

redis_configured = bool(REDIS_URL)

# ==========================================
# EMAIL (OPTIONAL NOTIFICATIONS)
# ==========================================

SMTP_HOST = _get("SMTP_HOST")
SMTP_PORT = _get_int("SMTP_PORT", 587)
SMTP_USERNAME = _get("SMTP_USERNAME")
SMTP_PASSWORD = _get("SMTP_PASSWORD")
SMTP_FROM = _get("SMTP_FROM")

email_configured = bool(SMTP_HOST and SMTP_FROM)


def feature_flags():
    """Report which optional integrations are active."""
    return {
        "auth_mode": "firebase" if firebase_configured else "local",
        "ai_copilot": ai_configured,
        "ai_provider": ai_provider_kind if ai_configured else None,
        "rag_embeddings": embeddings_configured,
        "vector_db": bool(VECTOR_DB_PROVIDER),
        "catalog_provider": bool(CATALOG_PROVIDER),
        "mission_metadata_provider": bool(MISSION_METADATA_PROVIDER),
        "redis": redis_configured,
        "email": email_configured,
    }
