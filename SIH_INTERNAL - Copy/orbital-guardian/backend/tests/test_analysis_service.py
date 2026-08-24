"""
Analysis pipeline service tests — TLE fetching is mocked offline;
SGP4 propagation and all downstream math run for real.
"""

import pytest

from backend.services.analysis_service import (
    ProgressReporter,
    STAGES,
    run_screening_pipeline,
)

TLE_A = {
    "name": "MOCK-SAT-A",
    "line1": ("1 25544U 98067A   26230.00000000  .00000000  00000-0  "
              "00000-0 0  9990"),
    "line2": ("2 25544  51.6400  10.0000 0005000  20.0000  30.0000 "
              "15.50000000123456"),
}

TLE_B = {
    # Same orbital plane as MOCK-SAT-A with a slight mean-motion offset;
    # nearly co-located at epoch, guaranteeing a flagged close approach.
    "name": "MOCK-DEB-A",
    "line1": ("1 28654U 98067A   26230.00000000  .00000000  00000-0  "
              "00000-0 0  9990"),
    "line2": ("2 28654  51.6400  10.0000 0005000  20.0000  30.0000 "
              "15.50300000123456"),
}


@pytest.fixture(autouse=True)
def mock_fetch_tle(monkeypatch):
    def fake_fetch(norad_id):
        if norad_id == 9999999:
            raise ValueError(f"No TLE found for NORAD ID {norad_id}")

        return TLE_B if norad_id == 28654 else TLE_A

    monkeypatch.setattr(
        "backend.services.analysis_service.fetch_tle", fake_fetch
    )


def _run(persist=False, reporter=None):
    return run_screening_pipeline(
        norad_ids=[25544, 28654],
        horizon_hours=12,
        step_minutes=2,
        screen_threshold_km=2000,
        top_n=10,
        reporter=reporter or ProgressReporter(),
        persist=persist,
    )


def test_pipeline_returns_ranked_alerts():
    result = _run()

    assert result["screening"]["objects_screened"] == 2
    assert result["screening"]["pairs_screened"] == 1

    assert isinstance(result["alerts"], list)
    assert len(result["alerts"]) >= 1

    alert = result["alerts"][0]

    for field in ("tca", "minimum_distance_km", "relative_velocity_km_s",
                  "risk_score", "risk_level", "risk_factors",
                  "confidence"):
        assert field in alert

    assert alert["minimum_distance_km"] > 0
    assert alert["relative_velocity_km_s"] > 0
    assert 0 <= alert["confidence"] <= 100


def test_pipeline_confidence_and_factors_present():
    alert = _run()["alerts"][0]

    assert alert["confidence_detail"]["basis"]
    assert alert["risk_factors"]["weights"]["distance"] == 0.5


def test_unknown_norad_reported_not_fatal():
    result = run_screening_pipeline(
        norad_ids=[25544, 28654, 9999999],
        horizon_hours=1,
        step_minutes=1,
        screen_threshold_km=500,
        top_n=5,
    )

    assert "9999999" in result["screening"]["fetch_errors"]
    assert result["screening"]["objects_screened"] == 2


def test_fewer_than_two_valid_objects_raises():
    with pytest.raises(ValueError):
        run_screening_pipeline(
            norad_ids=[25544, 9999999],
            horizon_hours=1,
            step_minutes=1,
            screen_threshold_km=100,
            top_n=5,
        )


def test_progress_reporter_emits_real_stages():
    events = []

    reporter = ProgressReporter(sink=lambda **e: events.append(e))

    _run(reporter=reporter)

    stages = [e.get("stage") for e in events if e.get("type") == "stage"]

    assert stages[0] == "FETCHING_ORBITAL_DATA"

    completed = [e for e in events if e.get("type") == "completed"]

    assert completed, "pipeline must emit a completed event"
    assert completed[0]["counters"].get("pairs_processed") == 1
    assert completed[0]["timings"]

    # Every emitted stage must be from the declared stage list.
    valid = {s for s, _ in [(s, s) for s in STAGES]}
    assert set(stages) <= valid
