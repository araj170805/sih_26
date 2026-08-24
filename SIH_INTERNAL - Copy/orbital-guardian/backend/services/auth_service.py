"""
Authentication service.

Deliberately dependency-free:
- Password hashing uses PBKDF2-HMAC-SHA256 (hashlib).
- JWT HS256 signing/verification uses hmac/hashlib/base64.

Both are well-understood standards; this avoids adding
native build dependencies to the project.
"""

import base64
import hashlib
import hmac
import json
import os
import secrets
import time

from backend.config import (
    ACCESS_TOKEN_EXPIRE_MINUTES,
    JWT_ALGORITHM,
    JWT_SECRET_KEY,
    PBKDF2_ITERATIONS,
    REFRESH_TOKEN_EXPIRE_DAYS,
)

# ==========================================
# PASSWORD HASHING (PBKDF2)
# ==========================================


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)

    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode(), salt, PBKDF2_ITERATIONS
    )

    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, iterations, salt_hex, digest_hex = stored.split("$")

        if scheme != "pbkdf2_sha256":
            return False

        digest = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode(),
            bytes.fromhex(salt_hex),
            int(iterations),
        )

        return hmac.compare_digest(digest.hex(), digest_hex)

    except (ValueError, AttributeError):
        return False


# ==========================================
# JWT (HS256)
# ==========================================


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _b64url_decode(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)


def create_access_token(user_id: int, role: str) -> str:
    now = int(time.time())

    header = {"alg": JWT_ALGORITHM, "typ": "JWT"}

    payload = {
        "sub": str(user_id),
        "role": role,
        "type": "access",
        "iat": now,
        "exp": now + ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        "jti": secrets.token_hex(8),
    }

    signing_input = (
        _b64url_encode(json.dumps(header, separators=(",", ":")).encode())
        + "."
        + _b64url_encode(json.dumps(payload, separators=(",", ":")).encode())
    )

    signature = hmac.new(
        JWT_SECRET_KEY.encode(), signing_input.encode(), hashlib.sha256
    ).digest()

    return f"{signing_input}.{_b64url_encode(signature)}"


def decode_token(token: str) -> dict | None:
    """
    Verify signature + expiry.
    Returns the payload, or None when invalid.
    """

    try:
        signing_input, _, signature_b64 = token.rpartition(".")

        expected = hmac.new(
            JWT_SECRET_KEY.encode(), signing_input.encode(), hashlib.sha256
        ).digest()

        if not hmac.compare_digest(expected, _b64url_decode(signature_b64)):
            return None

        header_b64, payload_b64 = signing_input.split(".", 1)

        payload = json.loads(_b64url_decode(payload_b64))

        if payload.get("exp", 0) < time.time():
            return None

        return payload

    except Exception:
        return None


# ==========================================
# REFRESH TOKENS (opaque, hashed at rest)
# ==========================================


def create_refresh_token() -> tuple[str, str, float]:
    """
    Returns (plaintext_token, sha256_hash, expires_at_epoch).
    Only the hash is stored in the database.
    """

    token = secrets.token_urlsafe(48)

    expires = time.time() + REFRESH_TOKEN_EXPIRE_DAYS * 86400

    token_hash = hashlib.sha256(token.encode()).hexdigest()

    return token, token_hash, expires


def hash_refresh_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def validate_registration(email: str, username: str, password: str):
    """Return an error string, or None when valid."""
    import re

    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email or ""):
        return "A valid email address is required."

    if not username or len(username) < 3 or len(username) > 80:
        return "Username must be 3-80 characters."

    if len(password or "") < 8:
        return "Password must be at least 8 characters."

    if not any(c.isdigit() for c in password):
        return "Password must contain at least one digit."

    return None
