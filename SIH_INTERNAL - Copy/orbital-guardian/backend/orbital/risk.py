def classify_risk(distance_km):
    """
    Prototype risk classification based on
    minimum separation distance.

    These thresholds are for prototype
    visualization and are NOT collision
    probability thresholds.
    """

    if distance_km <= 1:
        return "CRITICAL"

    if distance_km <= 10:
        return "HIGH"

    if distance_km <= 50:
        return "MONITOR"

    return "SAFE"


# ==========================================
# WEIGHTED PROTOTYPE RISK SCORE
# ==========================================
#
# Transparent screening/priority score in
# the range 0-100. NOT a collision
# probability.
#
# Factor weights (documented design choice):
#   distance          = 50%
#   relative velocity = 20%
#   time to TCA       = 20%
#   object types      = 10%
#
# Levels:
#   80-100 CRITICAL | 60-79 HIGH
#   30-59  MEDIUM   | 0-29   LOW
# ==========================================

SCORE_WEIGHTS = {
    "distance": 0.5,
    "relative_velocity": 0.2,
    "time_to_tca": 0.2,
    "object_type": 0.1,
}

TYPE_FACTORS = {"DEBRIS": 1.0, "ROCKET BODY": 0.8, "UNKNOWN": 0.5, "ACTIVE": 0.3}


def infer_object_type(name):
    """
    Heuristic object-type guess from the
    CelesTrak object name (TLE data carries
    no explicit type field).
    """

    upper = str(name).upper()

    if " DEB" in upper or upper.endswith("DEB"):
        return "DEBRIS"

    if "R/B" in upper:
        return "ROCKET BODY"

    return "ACTIVE"


def compute_risk_score(
    minimum_distance_km, relative_velocity_km_s, hours_to_tca, object_names=None
):
    """
    Explainable prototype conjunction risk score.

    Returns (score, level, factors) where
    factors exposes every normalized input so
    the UI/AI can explain exactly why an event
    received its score.
    """

    # Closer = higher risk. Saturates at 50 km.
    distance_factor = max(0.0, 1.0 - (minimum_distance_km / 50.0))

    # Faster closing = higher risk.
    # Saturates at typical LEO crossing speed.
    velocity_factor = min(relative_velocity_km_s / 15.0, 1.0)

    # Imminent = higher risk.
    # Saturates across the 72-hour horizon.
    time_factor = max(0.0, 1.0 - (hours_to_tca / 72.0))

    if object_names:
        type_factor = sum(
            TYPE_FACTORS.get(infer_object_type(name), TYPE_FACTORS["UNKNOWN"])
            for name in object_names
        ) / len(object_names)

    else:
        type_factor = TYPE_FACTORS["UNKNOWN"]

    raw_score = (
        SCORE_WEIGHTS["distance"] * distance_factor
        + SCORE_WEIGHTS["relative_velocity"] * velocity_factor
        + SCORE_WEIGHTS["time_to_tca"] * time_factor
        + SCORE_WEIGHTS["object_type"] * type_factor
    )

    score = round(raw_score * 100)

    if score >= 80:
        level = "CRITICAL"
    elif score >= 60:
        level = "HIGH"
    elif score >= 30:
        level = "MEDIUM"
    else:
        level = "LOW"

    factors = {
        "distance_factor": round(distance_factor, 3),
        "relative_velocity_factor": round(velocity_factor, 3),
        "time_to_tca_factor": round(time_factor, 3),
        "object_type_factor": round(type_factor, 3),
        "weights": SCORE_WEIGHTS,
    }

    return score, level, factors
