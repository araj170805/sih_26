import pytest
from fastapi.testclient import TestClient

from backend.api import app
from backend.database.connection import SessionLocal
from backend.database.models import Conjunction, Forecast

# ==========================================
# OFFLINE TLE MOCK
#
# Pipeline tests must not depend on live
# CelesTrak availability or rate limits.
# SGP4 propagation still runs for real.
# ==========================================

TLE_A = {
    "name": "MOCK-SAT-A",
    "line1": ("1 25544U 98067A   24001.00000000  .00000000  00000-0  00000-0 0  9990"),
    "line2": ("2 25544  51.6400  10.0000 0005000  20.0000  30.0000 15.50000000123456"),
}

TLE_B = {
    "name": "MOCK-SAT-B",
    "line1": ("1 28654U 05009A   24001.00000000  .00000000  00000-0  00000-0 0  9990"),
    "line2": ("2 28654  98.2000 120.0000 0011000  40.0000  60.0000 14.10000000123457"),
}


@pytest.fixture(autouse=True)
def mock_fetch_tle(monkeypatch):

    def fake_fetch(norad_id):

        # Keep unknown-ID behaviour realistic.
        if norad_id == 9999999:
            raise ValueError(f"No TLE found for NORAD ID {norad_id}")

        if norad_id == 28654:
            return TLE_B

        return TLE_A

    # backend.api is a package whose `app` attribute is the FastAPI
    # instance, which shadows submodule attribute access — resolve the
    # module explicitly through sys.modules.
    import importlib
    import sys

    importlib.import_module("backend.api.app")

    app_module = sys.modules["backend.api.app"]

    monkeypatch.setattr(app_module, "fetch_tle", fake_fetch)


@pytest.fixture(scope="module")
def client():

    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture(scope="module")
def record_count_before():

    db = SessionLocal()

    counts = (
        db.query(Forecast).order_by(Forecast.id.desc()).first(),
        db.query(Conjunction).order_by(Conjunction.id.desc()).first(),
    )

    db.close()

    return (counts[0].id if counts[0] else 0, counts[1].id if counts[1] else 0)


def cleanup_new_records(before):

    db = SessionLocal()

    before_f, before_c = before

    # Remove records created during the tests
    # (FK order: conjunctions first)
    (db.query(Conjunction).filter(Conjunction.id > before_c).delete())

    db.query(Forecast).filter(Forecast.id > before_f).delete()

    db.commit()
    db.close()


@pytest.fixture(scope="module")
def cleanup(request, record_count_before):

    yield

    cleanup_new_records(record_count_before)


# ==========================================
# BASIC ENDPOINTS
# ==========================================


def test_root(client):

    response = client.get("/")

    assert response.status_code == 200
    assert "running" in response.json()["message"]


def test_health(client):

    response = client.get("/health")

    assert response.status_code == 200

    body = response.json()

    assert body["status"] in ("healthy", "degraded")


# ==========================================
# VALIDATION / ERROR HANDLING
# ==========================================


def test_forecast_requires_objects(client):

    response = client.post("/forecast", json={"objects": []})

    assert response.status_code == 400


def test_conjunction_requires_two(client):

    response = client.post("/conjunction", json={"objects": [25544]})

    assert response.status_code == 400


def test_conjunction_rejects_duplicates(client):

    response = client.post("/conjunction", json={"objects": [25544, 25544]})

    assert response.status_code == 400


def test_invalid_norad_returns_404(client):

    response = client.post("/forecast", json={"objects": [9999999], "horizon_hours": 1})

    assert response.status_code == 404


# ==========================================
# FULL PIPELINE (network + SGP4 + DB)
# ==========================================


def test_forecast_endpoint(client, cleanup):

    response = client.post(
        "/forecast", json={"objects": [25544], "horizon_hours": 24, "step_minutes": 1}
    )

    assert response.status_code == 200

    body = response.json()

    assert body["forecast"]["total_points"] == 1441

    obj = body["objects"][0]

    assert obj["norad_id"] == 25544
    assert len(obj["points"]) == 1441

    point = obj["points"][0]

    assert "time" in point
    assert set(point["position"]) == {"x", "y", "z"}
    assert set(point["velocity"]) == {"x", "y", "z"}


def test_conjunction_endpoint_two_satellites(client, cleanup):

    response = client.post(
        "/conjunction",
        json={"objects": [25544, 28654], "horizon_hours": 24, "step_minutes": 1},
    )

    assert response.status_code == 200

    body = response.json()

    # Backward-compatible structure
    assert body["object_a"]["norad_id"] in (25544, 28654)
    assert body["object_b"]["norad_id"] in (25544, 28654)
    assert body["forecast"]["trajectory_points"] == 1441

    conj = body["conjunction"]

    assert conj["status"] in ("CRITICAL", "HIGH", "MONITOR", "SAFE")
    assert conj["minimum_distance_km"] > 0
    assert conj["refined"] is True

    # New multi-pair field: exactly one pair
    assert len(body["events"]) == 1


def test_history_endpoints(client):

    response = client.get("/forecasts?limit=5")

    assert response.status_code == 200

    body = response.json()

    assert "total" in body
    assert isinstance(body["forecasts"], list)

    response = client.get("/conjunctions?limit=5")

    assert response.status_code == 200

    body = response.json()

    assert "total" in body
    assert isinstance(body["conjunctions"], list)
