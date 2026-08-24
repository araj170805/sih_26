"""
Authentication endpoints.

POST /auth/register  — create account (first user becomes ADMIN)
POST /auth/login     — obtain access + refresh tokens
POST /auth/logout    — revoke a refresh token
POST /auth/refresh   — rotate tokens
GET  /auth/me        — current user profile
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.api.dependencies import get_current_user, require_user
from backend.database.connection import get_db
from backend.database.models import RefreshToken, User, UserRole
from backend.services.auth_service import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    hash_refresh_token,
    validate_registration,
    verify_password,
)

router = APIRouter(prefix="/auth", tags=["auth"])

bearer_scheme = HTTPBearer(auto_error=False)


class RegisterRequest(BaseModel):
    email: str = Field(..., max_length=255)
    username: str = Field(..., min_length=3, max_length=80)
    password: str = Field(..., min_length=8, max_length=128)


class LoginRequest(BaseModel):
    email: str
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


class LogoutRequest(BaseModel):
    refresh_token: str


def issue_tokens(user: User, db: Session) -> dict:
    access_token = create_access_token(user.id, user.role)

    refresh_plain, refresh_hash, expires = create_refresh_token()

    record = RefreshToken(
        user_id=user.id,
        token_hash=refresh_hash,
        expires_at=datetime.fromtimestamp(expires, tz=timezone.utc),
    )

    db.add(record)
    db.commit()

    return {
        "access_token": access_token,
        "refresh_token": refresh_plain,
        "token_type": "bearer",
        "expires_in_minutes": None,
        "user": {
            "id": user.id,
            "email": user.email,
            "username": user.username,
            "role": user.role,
        },
    }


@router.post("/register", status_code=201)
def register(request: RegisterRequest, db: Session = Depends(get_db)):
    error = validate_registration(request.email, request.username, request.password)

    if error:
        raise HTTPException(status_code=400, detail=error)

    if db.query(User).filter(User.email == request.email.lower()).first():
        raise HTTPException(status_code=409, detail="Email is already registered.")

    if db.query(User).filter(User.username == request.username).first():
        raise HTTPException(status_code=409, detail="Username is already taken.")

    # Bootstrap convenience: the very first account is ADMIN.
    is_first_user = db.query(User).count() == 0

    role = UserRole.ADMIN.value if is_first_user else UserRole.VIEWER.value

    user = User(
        email=request.email.lower(),
        username=request.username,
        password_hash=hash_password(request.password),
        role=role,
    )

    db.add(user)
    db.commit()
    db.refresh(user)

    return issue_tokens(user, db)


@router.post("/login")
def login(request: LoginRequest, db: Session = Depends(get_db)):
    user = (
        db.query(User).filter(User.email == request.email.lower().strip()).first()
    )

    if user is None or not verify_password(request.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password.")

    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account is disabled.")

    user.last_login_at = datetime.now(timezone.utc)

    db.commit()

    return issue_tokens(user, db)


@router.post("/refresh")
def refresh(request: RefreshRequest, db: Session = Depends(get_db)):
    token_hash = hash_refresh_token(request.refresh_token)

    record = (
        db.query(RefreshToken).filter(RefreshToken.token_hash == token_hash).first()
    )

    now_utc = datetime.now(timezone.utc)
    expires_at = record.expires_at if record else None

    if expires_at and expires_at.tzinfo is None:
        is_expired = expires_at < datetime.now()
    else:
        is_expired = expires_at < now_utc if expires_at else True

    if record is None or record.revoked or is_expired:
        raise HTTPException(
            status_code=401, detail="Refresh token is invalid or expired."
        )


    user = db.query(User).filter(User.id == record.user_id).first()

    if user is None or not user.is_active:
        raise HTTPException(status_code=401, detail="Account unavailable.")

    # Rotate: revoke the used token.
    record.revoked = True

    return issue_tokens(user, db)


@router.post("/logout")
def logout(
    request: LogoutRequest,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    token_hash = hash_refresh_token(request.refresh_token)

    record = (
        db.query(RefreshToken).filter(RefreshToken.token_hash == token_hash).first()
    )

    if record and record.user_id == user.id:
        record.revoked = True
        db.commit()

    return {"detail": "Logged out."}


class FirebaseSessionRequest(BaseModel):
    id_token: str


@router.post("/firebase-session")
def firebase_session(request: FirebaseSessionRequest, db=Depends(get_db)):
    """
    Exchange a Firebase ID token for the local operator profile.
    Called once by the frontend right after Firebase sign-in.
    Subsequent requests simply send the same ID token as Bearer.
    """

    from backend.config import firebase_configured
    from backend.services.firebase_auth import (
        upsert_firebase_user,
        verify_firebase_token,
    )

    if not firebase_configured:
        raise HTTPException(
            status_code=501,
            detail="Firebase authentication is not configured on the backend "
            "(set FIREBASE_PROJECT_ID in backend/.env).",
        )

    claims = verify_firebase_token(request.id_token)

    if claims is None:
        raise HTTPException(status_code=401, detail="Invalid Firebase ID token.")

    try:
        user = upsert_firebase_user(db, claims)

    except Exception as e:
        raise HTTPException(status_code=403, detail=str(e))

    return {
        "id": user.id,
        "email": user.email,
        "username": user.username,
        "role": user.role,
        "created_at": user.created_at.isoformat(),
    }


@router.get("/me")
def me(user: User = Depends(require_user)):
    return {
        "id": user.id,
        "email": user.email,
        "username": user.username,
        "role": user.role,
        "created_at": user.created_at.isoformat(),
        "last_login_at": (
            user.last_login_at.isoformat() if user.last_login_at else None
        ),
    }
