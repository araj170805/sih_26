"""
Firebase Authentication verification (backend).

Verifies Firebase ID tokens issued by the frontend without the
heavy firebase-admin SDK: signatures are checked against Google's
public x509 certificates (RS256), plus issuer/audience/expiry.

Required configuration:
    FIREBASE_PROJECT_ID=your-firebase-project-id

Tokens are verified, then mapped to a local User row so roles,
watchlists and notifications keep working unchanged.
"""

import secrets
import time

import jwt
import requests
from cryptography.hazmat.primitives.serialization import load_pem_public_key
from cryptography.x509 import load_pem_x509_certificate

from backend.config import FIREBASE_PROJECT_ID
from backend.services.auth_service import hash_password

CERTS_URL = (
    "https://www.googleapis.com/robot/v1/metadata/x509/"
    "securetoken@system.gserviceaccount.com"
)

ISSUER_TEMPLATE = "https://securetoken.google.com/{project_id}"

_cert_cache = {"certs": None, "fetched_at": 0.0}

_CERT_TTL = 3600  # rotate at least daily per Google docs; 1 h is safe


class FirebaseError(Exception):
    pass


def _get_public_keys() -> dict:
    """Fetch and cache Google's signing certificates -> RSA public keys."""

    now = time.time()

    if _cert_cache["certs"] is None or now - _cert_cache["fetched_at"] > _CERT_TTL:
        response = requests.get(CERTS_URL, timeout=10)

        if response.status_code != 200:
            raise FirebaseError(
                f"Could not fetch Firebase public keys "
                f"(HTTP {response.status_code})."
            )

        keys = {}

        for kid, pem in response.json().items():
            try:
                # Google returns X.509 certificates — extract the
                # contained RSA public key.
                keys[kid] = load_pem_x509_certificate(
                    pem.encode()
                ).public_key()

            except ValueError:
                keys[kid] = load_pem_public_key(pem.encode())

        _cert_cache["certs"] = keys
        _cert_cache["fetched_at"] = now

    return _cert_cache["certs"]


def verify_firebase_token(id_token: str) -> dict | None:
    """
    Verify a Firebase ID token.
    Returns the token claims on success, None when invalid.
    """

    if not id_token or not FIREBASE_PROJECT_ID:
        return None

    try:
        header = jwt.get_unverified_header(id_token)

        kid = header.get("kid")

        if not kid:
            return None

        public_key = _get_public_keys().get(kid)

        if public_key is None:
            # Key rotated since cache — refresh once.
            _cert_cache["certs"] = None
            public_key = _get_public_keys().get(kid)

            if public_key is None:
                return None

        claims = jwt.decode(
            id_token,
            public_key,
            algorithms=["RS256"],
            audience=FIREBASE_PROJECT_ID,
            issuer=ISSUER_TEMPLATE.format(project_id=FIREBASE_PROJECT_ID),
            options={"require": ["exp", "iat", "aud", "iss", "sub"]},
        )

        return claims

    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None
    except Exception as e:
        print(f"[FIREBASE] Verification error: {e}")
        return None


def upsert_firebase_user(db, claims: dict):
    """
    Map a verified Firebase identity onto the local users table.

    SINGLE-ROLE MODE: every authenticated operator gets full
    platform access. The role column remains for future
    fine-grained control but no longer gates features.
    """

    from backend.database.models import User, UserRole

    firebase_uid = claims["sub"]
    email = (claims.get("email") or "").lower()

    user = db.query(User).filter(User.email == email).first() if email else None

    if user is None:
        username = (
            claims.get("name")
            or (email.split("@")[0] if email else f"operator_{firebase_uid[:8]}")
        )

        # Ensure username uniqueness.
        base_username = username[:80]
        suffix = 1

        while db.query(User).filter(User.username == username).first():
            username = f"{base_username[:70]}_{suffix}"
            suffix += 1

        user = User(
            email=email or f"{firebase_uid}@firebase.local",
            username=username,
            password_hash=hash_password(secrets.token_urlsafe(32)),
            role=UserRole.ADMIN.value,
        )

        db.add(user)
        db.commit()
        db.refresh(user)

    elif not user.is_active:
        raise FirebaseError("Account is disabled.")

    elif user.role != UserRole.ADMIN.value:
        # Upgrade legacy role-limited accounts to full access.
        user.role = UserRole.ADMIN.value
        db.commit()

    return user
