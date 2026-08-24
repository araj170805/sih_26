from datetime import timezone

from sgp4.api import jday


def propagate(satellite, time):
    """
    Propagate a satellite to a specific UTC time.

    Returns:
        position: km
        velocity: km/s
    """

    if time.tzinfo is None:
        time = time.replace(tzinfo=timezone.utc)

    time = time.astimezone(timezone.utc)

    jd, fr = jday(
        time.year,
        time.month,
        time.day,
        time.hour,
        time.minute,
        time.second + time.microsecond / 1_000_000,
    )

    error, position, velocity = satellite.sgp4(jd, fr)

    if error != 0:
        raise RuntimeError(f"SGP4 propagation error: {error}")

    return position, velocity
