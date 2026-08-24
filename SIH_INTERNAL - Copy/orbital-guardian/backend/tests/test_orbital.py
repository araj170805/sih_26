from datetime import datetime, timedelta, timezone

import pytest
from sgp4.api import Satrec, jday

from backend.orbital.conjunction import calculate_distance, find_closest_approach
from backend.orbital.propagator import propagate
from backend.orbital.tle_parser import parse_tle
from backend.orbital.trajectory import generate_trajectory

# Known ISS TLE (epoch 2024-01-01)
ISS_LINE1 = "1 25544U 98067A   24001.00000000  .00016717  00000+0  30777-3 0  9995"

ISS_LINE2 = "2 25544  51.6416 247.4627 0006703 130.5360 325.0288 15.72125391563537"


# ==========================================
# SGP4 NUMERICAL VERIFICATION
# ==========================================


def test_sgp4_propagation_magnitude():

    satellite = parse_tle("ISS", ISS_LINE1, ISS_LINE2)["satellite"]

    t = datetime(2024, 1, 1, 1, 0, tzinfo=timezone.utc)
    position, velocity = propagate(satellite, t)

    r = (position[0] ** 2 + position[1] ** 2 + position[2] ** 2) ** 0.5
    v = (velocity[0] ** 2 + velocity[1] ** 2 + velocity[2] ** 2) ** 0.5

    # LEO altitude sanity: 6500–7500 km from geocentre,
    # orbital speed ~7.5 km/s.
    assert 6500 < r < 7500
    assert 7.0 < v < 8.0


def test_sgp4_reference_value():

    # Compare directly against the sgp4 library
    satellite = Satrec.twoline2rv(ISS_LINE1, ISS_LINE2)

    jd, fr = jday(2024, 1, 1, 1, 0, 0)
    error, position, velocity = satellite.sgp4(jd, fr)

    assert error == 0

    t = datetime(2024, 1, 1, 1, 0, tzinfo=timezone.utc)
    p2, v2 = propagate(satellite, t)

    assert p2 == pytest.approx(position)
    assert v2 == pytest.approx(velocity)


def test_trajectory_length_1441():

    satellite = parse_tle("ISS", ISS_LINE1, ISS_LINE2)["satellite"]

    start = datetime(2024, 1, 1, tzinfo=timezone.utc)

    trajectory = generate_trajectory(satellite, start, hours=24, step_minutes=1)

    assert len(trajectory) == 1441
    assert trajectory[0]["time"] == start
    assert trajectory[-1]["time"] == start + timedelta(hours=24)


def test_find_closest_approach_structure():

    satellite_a = parse_tle("A", ISS_LINE1, ISS_LINE2)["satellite"]

    start = datetime(2024, 1, 1, tzinfo=timezone.utc)

    trajectory_a = generate_trajectory(satellite_a, start, hours=2)
    trajectory_b = generate_trajectory(satellite_a, start, hours=2)

    result = find_closest_approach(trajectory_a, trajectory_b, satellite_a, satellite_a)

    # Same satellite vs itself: distance ~0 at every step
    assert result["minimum_distance_km"] < 1.0
    assert result["refined"] is True
    assert result["status"] in ("CRITICAL", "HIGH", "MONITOR", "SAFE")
    assert result["tca"] is not None


def test_calculate_distance():

    assert calculate_distance((0, 0, 0), (3, 4, 0)) == 5.0
