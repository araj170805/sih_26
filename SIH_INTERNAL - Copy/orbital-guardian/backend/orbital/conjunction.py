from datetime import timedelta

from .propagator import propagate
from .risk import classify_risk


def calculate_distance(position_a, position_b):
    """
    Calculate Euclidean distance between
    two positions in kilometres.
    """

    dx = position_a[0] - position_b[0]
    dy = position_a[1] - position_b[1]
    dz = position_a[2] - position_b[2]

    return (dx**2 + dy**2 + dz**2) ** 0.5


def find_closest_approach(
    trajectory_a, trajectory_b, satellite_a, satellite_b, refinement_seconds=1
):
    """
    Find closest approach between two satellites.

    Stage 1:
        Coarse search using 1-minute trajectory.

    Stage 2:
        Refine around the approximate TCA
        using SGP4 at a finer time resolution.
    """

    if len(trajectory_a) != len(trajectory_b):
        raise ValueError("Trajectories must have the same number of points.")

    # =========================================
    # STAGE 1 — COARSE SEARCH
    # =========================================

    minimum_distance = float("inf")
    closest_index = None

    for index, (point_a, point_b) in enumerate(zip(trajectory_a, trajectory_b)):
        distance = calculate_distance(point_a["position"], point_b["position"])

        if distance < minimum_distance:
            minimum_distance = distance
            closest_index = index

    approximate_tca = trajectory_a[closest_index]["time"]

    # =========================================
    # STAGE 2 — FINE SEARCH
    # =========================================

    # Search ±1 minute around the
    # approximate TCA.

    search_start = approximate_tca - timedelta(minutes=1)

    search_end = approximate_tca + timedelta(minutes=1)

    refined_distance = float("inf")
    refined_tca = None
    refined_position_a = None
    refined_position_b = None
    refined_velocity_a = None
    refined_velocity_b = None

    current_time = search_start

    while current_time <= search_end:
        position_a, velocity_a = propagate(satellite_a, current_time)

        position_b, velocity_b = propagate(satellite_b, current_time)

        distance = calculate_distance(position_a, position_b)

        if distance < refined_distance:
            refined_distance = distance
            refined_tca = current_time

            refined_position_a = position_a
            refined_position_b = position_b

            refined_velocity_a = velocity_a
            refined_velocity_b = velocity_b

        current_time += timedelta(seconds=refinement_seconds)

    # =========================================
    # RELATIVE VELOCITY AT TCA
    # =========================================

    relative_velocity_km_s = (
        (refined_velocity_a[0] - refined_velocity_b[0]) ** 2
        + (refined_velocity_a[1] - refined_velocity_b[1]) ** 2
        + (refined_velocity_a[2] - refined_velocity_b[2]) ** 2
    ) ** 0.5

    # =========================================
    # RESULT
    # =========================================

    status = classify_risk(refined_distance)

    return {
        "tca": refined_tca,
        "minimum_distance_km": refined_distance,
        "position_a": refined_position_a,
        "position_b": refined_position_b,
        "velocity_a": refined_velocity_a,
        "velocity_b": refined_velocity_b,
        "relative_velocity_km_s": relative_velocity_km_s,
        "coarse_tca": approximate_tca,
        "coarse_distance_km": minimum_distance,
        "status": status,
        "refined": True,
    }
