"""
FastAPI authentication dependencies and RBAC guards.
"""

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from backend.config import firebase_configured
from backend.database.connection import get_db
from backend.database.models import User, UserRole
from backend.services.auth_service import decode_token

bearer_scheme = HTTPBearer(auto_error=False)

ROLE_ORDER = {
    UserRole.VIEWER.value: 0,
    UserRole.ANALYST.value: 1,
    UserRole.ADMIN.value: 2,
}


def _resolve_token(
    credentials: HTTPAuthorizationCredentials | None,
    query_token: str | None,
) -> str | None:
    """
    Authorization: Bearer <token> first;
    ?access_token= fallback for EventSource (SSE),
    which cannot set custom headers.
    """

    if credentials is not None:
        return credentials.credentials

    return query_token


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    query_token: str | None = None,
    db: Session = Depends(get_db),
) -> User | None:
    """
    Resolve the current user from the Authorization header
    (or access_token query parameter).

    Priority:
      1. Firebase ID token  (when FIREBASE_PROJECT_ID is configured)
      2. Local HS256 JWT    (legacy programmatic access)

    Returns None when no/invalid token is presented so that
    public endpoints can degrade gracefully.
    """

    token = _resolve_token(credentials, query_token)

    if not token:
        return None

    # ---- 1. Firebase ID token ----
    if firebase_configured:
        from backend.services.firebase_auth import (
            upsert_firebase_user,
            verify_firebase_token,
        )

        claims = verify_firebase_token(token)

        if claims is not None:
            try:
                return upsert_firebase_user(db, claims)

            except Exception as e:
                print(f"[FIREBASE] User mapping failed: {e}")

                raise HTTPException(
                    status_code=403, detail="Account unavailable."
                )

        # Not a Firebase token — fall through to local JWT so that
        # programmatic/legacy sessions keep working.

    # ---- 2. Local JWT ----
    payload = decode_token(token)

    if not payload or payload.get("type") != "access":
        return None

    user = db.query(User).filter(User.id == int(payload["sub"])).first()

    if user is None or not user.is_active:
        return None

    return user


def require_user(user: User | None = Depends(get_current_user)) -> User:
    if user is None:
        raise HTTPException(
            status_code=401, detail="Authentication required."
        )

    return user


def require_role(minimum_role: str):
    """
    Dependency factory: enforce a minimum role level.
    VIEWER < ANALYST < ADMIN (hierarchy).
    """

    def checker(user: User = Depends(require_user)) -> User:
        if ROLE_ORDER.get(user.role, -1) < ROLE_ORDER[minimum_role]:
            raise HTTPException(
                status_code=403,
                detail=f"This action requires the {minimum_role} role.",
            )

        return user

    return checker
