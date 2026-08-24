from datetime import timedelta

from .propagator import propagate


def generate_trajectory(satellite, start_time, hours=24, step_minutes=1):
    """
    Generate a future satellite trajectory.

    Parameters:
        satellite: SGP4 satellite object
        start_time: UTC datetime
        hours: prediction horizon
        step_minutes: time resolution

    Returns:
        List of trajectory points.
    """

    trajectory = []

    total_steps = int(hours * 60 / step_minutes)

    for i in range(total_steps + 1):
        current_time = start_time + timedelta(minutes=i * step_minutes)

        position, velocity = propagate(satellite, current_time)

        trajectory.append(
            {"time": current_time, "position": position, "velocity": velocity}
        )

    return trajectory
