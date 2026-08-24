"""
Deterministic data-confidence assessment.

Confidence reflects ONLY the freshness of the orbital
elements used for a prediction. It says nothing about
the probability of collision and never invents values:
a missing epoch yields UNKNOWN confidence.
"""

from datetime import datetime, timezone


def _parse_epoch(epoch_iso: str | None) -> datetime | None:
    if not epoch_iso:
        return None

    try:
        dt = datetime.fromisoformat(epoch_iso)

        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)

        return dt

    except (ValueError, TypeError):
        return None


def tle_age_hours(epoch_iso: str | None, reference: datetime) -> float | None:
    epoch = _parse_epoch(epoch_iso)

    if epoch is None:
        return None

    return max((reference - epoch).total_seconds() / 3600.0, 0.0)


def freshness_label(age_hours: float | None) -> str:
    if age_hours is None:
        return "UNKNOWN"

    if age_hours <= 8:
        return "FRESH"

    if age_hours <= 24:
        return "AGING"

    return "STALE"


def compute_confidence(
    epoch_a_iso: str | None,
    epoch_b_iso: str | None,
    reference: datetime,
) -> tuple[float, dict]:
    """
    Deterministic 0-100 confidence derived from TLE age
    of both objects. The older element set dominates.

    Basis (documented heuristic):
      <= 4 h  -> ~95      <= 12 h -> ~85
      <= 24 h -> ~70      <= 48 h -> ~50
      else    -> decays linearly to a floor of 15.
    """

    age_a = tle_age_hours(epoch_a_iso, reference)
    age_b = tle_age_hours(epoch_b_iso, reference)

    ages = [age for age in (age_a, age_b) if age is not None]

    if not ages:
        return 50.0, {
            "freshness": "UNKNOWN",
            "tle_age_hours": None,
            "basis": "TLE epochs unavailable; default neutral confidence.",
        }

    worst = max(ages)

    if worst <= 4:
        score = 95.0
    elif worst <= 12:
        score = 85.0
    elif worst <= 24:
        score = 70.0
    elif worst <= 48:
        score = 50.0
    else:
        score = max(15.0, 50.0 - (worst - 48) * 0.5)

    score = round(score, 1)

    return score, {
        "freshness": freshness_label(worst),
        "tle_age_hours": round(worst, 2),
        "tle_age_hours_a": (
            round(age_a, 2) if age_a is not None else None
        ),
        "tle_age_hours_b": (
            round(age_b, 2) if age_b is not None else None
        ),
        "basis": "Confidence decreases with element-set age "
        "(older epoch dominates); deterministic mapping.",
    }
