"""
Authentication endpoint tests (require a running PostgreSQL).
"""

import pytest
from fastapi.testclient import TestClient

from backend.database.connection import SessionLocal
from backend.database.models import RefreshToken, User

from backend.api.app import app


@pytest.fixture()
def client():
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture(autouse=True)
def cleanup_users():
    yield

    db = SessionLocal()

    try:
        db.query(RefreshToken).delete()
        db.query(User).filter(User.email.like("pytest-%")).delete()
        db.commit()
    finally:
        db.close()


def _register(client, suffix="1"):
    return client.post(
        "/auth/register",
        json={
            "email": f"pytest-user{suffix}@example.com",
            "username": f"pytest_user{suffix}",
            "password": "Passw0rd123",
        },
    )


def test_register_login_me_flow(client):
    response = _register(client, "a")

    assert response.status_code == 201, response.text

    tokens = response.json()

    assert tokens["access_token"]
    assert tokens["refresh_token"]
    assert tokens["user"]["role"] in ("ADMIN", "VIEWER")

    headers = {"Authorization": f"Bearer {tokens['access_token']}"}

    me = client.get("/auth/me", headers=headers)

    assert me.status_code == 200
    assert me.json()["email"] == "pytest-usera@example.com"


def test_duplicate_registration_rejected(client):
    first = _register(client, "b")

    assert first.status_code == 201

    second = _register(client, "b")

    assert second.status_code == 409


def test_login_wrong_password(client):
    _register(client, "c")

    response = client.post(
        "/auth/login",
        json={"email": "pytest-userc@example.com", "password": "WrongPass1"},
    )

    assert response.status_code == 401


def test_protected_route_requires_token(client):
    response = client.get("/watchlists")

    # Guests may list nothing without auth -> 401.
    assert response.status_code == 401


def test_viewer_cannot_start_analysis(client):
    registration = _register(client, "d")

    if registration.json()["user"]["role"] != "VIEWER":
        pytest.skip("first user is ADMIN; role test needs a second account")

    headers = {
        "Authorization": f"Bearer {registration.json()['access_token']}"
    }

    response = client.post(
        "/analysis/start",
        json={"objects": [25544, 28654]},
        headers=headers,
    )

    assert response.status_code == 403


def test_refresh_rotation(client):
    registration = _register(client, "e")

    refresh_token = registration.json()["refresh_token"]

    rotated = client.post(
        "/auth/refresh", json={"refresh_token": refresh_token}
    )

    assert rotated.status_code == 200
    assert rotated.json()["access_token"]

    # Old token must now be revoked.
    reuse = client.post("/auth/refresh", json={"refresh_token": refresh_token})

    assert reuse.status_code == 401
