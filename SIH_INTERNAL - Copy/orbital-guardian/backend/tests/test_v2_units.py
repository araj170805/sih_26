"""
Unit tests for v2.0 additions that do not require the database:
auth service, confidence module, risk scoring, RAG retrieval and
the deterministic copilot explainers.
"""

import time
from datetime import datetime, timedelta, timezone

import pytest

from backend.intelligence.confidence import (
    compute_confidence,
    freshness_label,
    tle_age_hours,
)
from backend.rag.copilot import explain_event_deterministic, explain_object_deterministic
from backend.rag.retriever import retrieve
from backend.services.auth_service import (
    create_access_token,
    decode_token,
    hash_password,
    hash_refresh_token,
    validate_registration,
    verify_password,
)


# ==========================================
# AUTH SERVICE
# ==========================================


def test_password_hash_roundtrip():
    stored = hash_password("Sup3rSecret!")

    assert stored != "Sup3rSecret!"
    assert verify_password("Sup3rSecret!", stored)
    assert not verify_password("wrong", stored)


def test_password_hash_salted():
    assert hash_password("abc12345") != hash_password("abc12345")


def test_jwt_roundtrip_and_expiry():
    token = create_access_token(42, "ANALYST")

    payload = decode_token(token)

    assert payload is not None
    assert payload["sub"] == "42"
    assert payload["role"] == "ANALYST"
    assert payload["exp"] > time.time()


def test_jwt_tamper_rejected():
    token = create_access_token(1, "VIEWER")

    assert decode_token(token[:-2] + "xx") is None
    assert decode_token("garbage.token.here") is None


def test_refresh_hash_stable():
    assert hash_refresh_token("tok") == hash_refresh_token("tok")
    assert hash_refresh_token("tok") != hash_refresh_token("tok2")


def test_registration_validation():
    assert validate_registration("a@b.co", "alice", "pass1234") is None

    for email, username, password in [
        ("not-an-email", "alice", "pass1234"),
        ("a@b.co", "ab", "pass1234"),
        ("a@b.co", "alice", "short1"),
        ("a@b.co", "alice", "nodigitshere"),
        ("", "", ""),
    ]:
        assert validate_registration(email, username, password) is not None


# ==========================================
# CONFIDENCE / FRESHNESS
# ==========================================

NOW = datetime.now(timezone.utc)


def test_tle_age_and_freshness():
    epoch = NOW - timedelta(hours=3)

    age = tle_age_hours(epoch.isoformat(), NOW)

    assert 2.9 < age < 3.01
    assert freshness_label(age) == "FRESH"

    assert freshness_label(tle_age_hours(
        (NOW - timedelta(hours=20)).isoformat(), NOW)) == "AGING"
    assert freshness_label(tle_age_hours(
        (NOW - timedelta(days=5)).isoformat(), NOW)) == "STALE"
    assert freshness_label(None) == "UNKNOWN"


def test_confidence_monotonic_with_age():
    recent = compute_confidence(
        (NOW - timedelta(hours=2)).isoformat(),
        (NOW - timedelta(hours=2)).isoformat(),
        NOW,
    )

    old = compute_confidence(
        (NOW - timedelta(days=10)).isoformat(),
        (NOW - timedelta(days=10)).isoformat(),
        NOW,
    )

    unknown = compute_confidence(None, None, NOW)

    assert recent[0] > old[0]
    assert recent[0] >= 90
    assert old[0] < 40
    assert unknown[0] == 50.0
    assert unknown[1]["freshness"] == "UNKNOWN"


# ==========================================
# RAG RETRIEVER
# ==========================================


def test_retriever_finds_relevant_docs():
    hits = retrieve("what is SGP4 propagation")

    assert hits, "expected knowledge base hits"
    assert any("sgp4" in h["source"].lower() or "SGP4" in h["title"]
               for h in hits)

    assert retrieve("", top_k=3) == []


def test_retriever_glossary():
    hits = retrieve("TCA miss distance definition")

    assert hits
    assert all(set(h) >= {"title", "category", "source", "excerpt"}
               for h in hits)


# ==========================================
# DETERMINISTIC COPILOT EXPLAINERS
# ==========================================

EVENT = {
    "minimum_distance_km": 0.8,
    "relative_velocity_km_s": 12.0,
    "risk_score": 78,
    "risk_level": "HIGH",
    "risk_factors": {
        "distance_factor": 0.984,
        "relative_velocity_factor": 0.8,
        "time_to_tca_factor": 0.6,
        "object_type_factor": 0.65,
        "weights": {
            "distance": 0.5,
            "relative_velocity": 0.2,
            "time_to_tca": 0.2,
            "object_type": 0.1,
        },
    },
}


def test_explain_event_contains_real_numbers():
    text = explain_event_deterministic(EVENT)

    assert "0.80 km" in text
    assert "12.0 km/s" in text
    assert "78/100" in text
    assert "HIGH" in text
    # Must include the disclaimer about Pc.
    assert "NOT" in text and "probability of collision" in text


def test_explain_event_identifies_dominant_factor():
    text = explain_event_deterministic(EVENT)

    assert "miss distance" in text.lower()
    assert "primarily" in text.lower()


def test_explain_object_uses_profile_only():
    profile = {
        "identity": {"object_name": "MOCK SAT", "norad_id": 999,
                     "object_type": "PAYLOAD"},
        "status": {"status": "OPERATIONAL", "basis": "Verified public record"},
        "mission": {"mission_name": "Test Mission",
                    "mission_description": "Testing."},
        "live_orbit": {"altitude_km": 510.2, "inclination_deg": 97.6,
                       "orbital_period_min": 94.7},
        "data_quality": {"freshness": "FRESH", "tle_age_hours": 2.1,
                         "confidence_score": 95.0},
    }

    text = explain_object_deterministic(profile)

    assert "MOCK SAT" in text
    assert "510.2" in text
    assert "FRESH" in text
    assert "Test Mission" in text


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
