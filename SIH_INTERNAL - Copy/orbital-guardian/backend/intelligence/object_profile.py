"""
Object Intelligence Service.

Aggregates a unified object profile from layered providers:

    1. DB cache (object_profiles, TTL)
    2. Live TLE (existing data_fetcher chain)
    3. Optional catalog metadata provider (if configured)
    4. Curated local registry
    5. Explicit 'unavailable' results — never invented data

All orbital quantities are computed deterministically from the
actual TLE via SGP4 / Brouwer mean elements.
"""

import math
import time
from datetime import datetime, timezone

from backend.config import (
    CATALOG_API_BASE_URL,
    CATALOG_API_KEY,
    CATALOG_PROVIDER,
    MISSION_METADATA_API_BASE_URL,
    MISSION_METADATA_API_KEY,
    MISSION_METADATA_PROVIDER,
    feature_flags,
)
from backend.intelligence.confidence import compute_confidence, freshness_label, tle_age_hours
from backend.intelligence.curated import constellation_hint, lookup as curated_lookup
from backend.orbital.data_fetcher import fetch_tle
from backend.orbital.propagator import propagate
from backend.orbital.risk import infer_object_type

PROFILE_TTL_SECONDS = 6 * 3600

EARTH_RADIUS_KM = 6378.137
MU_KM3_S2 = 398600.4418


# ==========================================
# ORBITAL ELEMENTS (from Satrec)
# ==========================================


def orbital_elements(satrec) -> dict:
    """
    Deterministic mean elements from the SGP4 model:
      - inclination (deg), eccentricity
      - apogee/perigee altitude (km)
      - period (min)
    """

    inclination_deg = math.degrees(satrec.inclo)
    eccentricity = satrec.ecco

    n_rad_s = satrec.no_kozai / 60.0  # Kozai mean motion rad/min -> rad/s

    semi_major_km = (MU_KM3_S2 / (n_rad_s**2)) ** (1.0 / 3.0)

    apogee_alt = semi_major_km * (1 + eccentricity) - EARTH_RADIUS_KM
    perigee_alt = semi_major_km * (1 - eccentricity) - EARTH_RADIUS_KM

    period_min = (2 * math.pi) / n_rad_s / 60.0 if n_rad_s else None

    return {
        "inclination_deg": round(inclination_deg, 4),
        "eccentricity": round(eccentricity, 7),
        "apogee_altitude_km": round(apogee_alt, 1),
        "perigee_altitude_km": round(perigee_alt, 1),
        "orbital_period_min": round(period_min, 2) if period_min else None,
    }


def _gmst(jd: float) -> float:
    """Greenwich mean sidereal angle (radians), IAU-82 approximation."""
    t = (jd - 2451545.0) / 36525.0
    gmst_deg = (
        280.46061837 + 360.98564736629 * (jd - 2451545.0) + 0.000387933 * t * t
        - t * t * t / 38710000.0
    ) % 360.0
    return math.radians(gmst_deg)


def subsatellite_point(position_teme: list[float], jd: float) -> dict:
    """
    TEME km position -> geodetic sub-satellite point.
    Uses GMST rotation (deterministic; adequate for display).
    """

    theta = _gmst(jd)

    x = position_teme[0]
    y = position_teme[1]
    z = position_teme[2]

    # Rotate TEME -> pseudo-ECEF
    xe = x * math.cos(theta) + y * math.sin(theta)
    ye = -x * math.sin(theta) + y * math.cos(theta)

    r_xy = math.hypot(xe, ye)
    lon = math.degrees(math.atan2(ye, xe))
    lat = math.degrees(math.atan2(z, r_xy))

    # First-order geodetic correction (flattening).
    f = 1.0 / 298.257223563
    lat_geodetic = math.degrees(
        math.atan((z / max(r_xy, 1e-9)) / (1 - f) ** 2)
    )

    altitude = math.sqrt(x**2 + y**2 + z**2) - EARTH_RADIUS_KM

    return {
        "latitude_deg": round(lat_geodetic, 3),
        "longitude_deg": round(((lon + 180) % 360) - 180, 3),
        "altitude_km": round(altitude, 1),
    }


# ==========================================
# OPTIONAL EXTERNAL PROVIDERS
# ==========================================


def fetch_catalog_metadata(norad_id: int) -> dict | None:
    """
    Optional external catalog provider.
    Returns explicit unavailable marker when not configured.
    """

    if not (CATALOG_PROVIDER and CATALOG_API_BASE_URL):
        return {"available": False, "reason": "Provider not configured"}

    try:
        import requests  # noqa: PLC0415

        headers = {}

        if CATALOG_API_KEY:
            headers["Authorization"] = f"Token {CATALOG_API_KEY}"

        response = requests.get(
            f"{CATALOG_API_BASE_URL}/satellites/{norad_id}",
            headers=headers,
            timeout=10,
        )

        if response.status_code != 200:
            return {
                "available": False,
                "reason": f"Provider returned HTTP {response.status_code}",
            }

        data = response.json()

        return {
            "available": True,
            "provider": CATALOG_PROVIDER,
            "names": data.get("names"),
            "countries": data.get("countries"),
            "launched": data.get("launched"),
            "statuses": data.get("statuses"),
        }

    except Exception as e:
        return {"available": False, "provider_error": str(e)[:200]}


def fetch_mission_metadata(norad_id: int) -> dict | None:
    if not (MISSION_METADATA_PROVIDER and MISSION_METADATA_API_BASE_URL):
        return {"available": False, "reason": "Provider not configured"}

    try:
        import requests  # noqa: PLC0415

        headers = {}

        if MISSION_METADATA_API_KEY:
            headers["Authorization"] = f"Bearer {MISSION_METADATA_API_KEY}"

        response = requests.get(
            f"{MISSION_METADATA_API_BASE_URL}/{norad_id}",
            headers=headers,
            timeout=10,
        )

        if response.status_code != 200:
            return {
                "available": False,
                "reason": f"Provider returned HTTP {response.status_code}",
            }

        data = response.json()

        return {"available": True, "provider": MISSION_METADATA_PROVIDER, **data}

    except Exception as e:
        return {"available": False, "provider_error": str(e)[:200]}


# ==========================================
# END-OF-LIFE ESTIMATION
# ==========================================


def estimate_orbital_lifetime(perigee_alt_km: float | None) -> dict:
    """
    Coarse orbital-lifetime band from perigee altitude.

    This is a DOCUMENTED HEURISTIC for display only — real decay
    prediction requires Space-Track TIP messages or numerical
    drag integration. Solar activity can shift bands by 2-3x.
    """

    if perigee_alt_km is None:
        return {
            "estimated_lifetime": "UNKNOWN",
            "basis": "Perigee altitude unavailable.",
        }

    bands = [
        (250, "Months"),
        (300, "1 – 3 years"),
        (350, "2 – 8 years"),
        (400, "5 – 15 years"),
        (500, "10 – 30 years"),
        (600, "25 – 70 years"),
        (700, "50 – 150 years"),
        (800, "100+ years (centuries for many)"),
    ]

    for threshold, label in bands:
        if perigee_alt_km < threshold:
            return {
                "estimated_lifetime": label,
                "basis": (
                    f"Heuristic drag-decay band for ~{int(perigee_alt_km)} km "
                    "perigee (varies strongly with solar activity and "
                    "object area-to-mass ratio)."
                ),
            }

    return {
        "estimated_lifetime": "Centuries+ (effectively permanent on "
        "human timescales without deorbit)",
        "basis": (
            f"Perigee ~{int(perigee_alt_km)} km — atmospheric drag is "
            "negligible at this altitude."
        ),
    }


# ==========================================
# UNIFIED PROFILE BUILDER
# ==========================================


def build_object_profile(norad_id: int, db=None, use_cache=True) -> dict:
    """
    Build the unified object intelligence profile.

    `db` is an optional SQLAlchemy session used for the
    profile cache and conjunction context lookups.
    """

    fetched_at = datetime.now(timezone.utc)

    # ---------------------------------------------
    # 1. CACHE
    # ---------------------------------------------

    if use_cache and db is not None:
        cached = _read_cache(db, norad_id)

        if cached is not None:
            return cached

    sources = []

    # ---------------------------------------------
    # 2. LIVE TLE + ORBIT
    # ---------------------------------------------

    try:
        tle = fetch_tle(norad_id)
    except ValueError:
        raise KeyError(f"No TLE data found for NORAD {norad_id}")
    except Exception as e:
        raise RuntimeError(f"TLE provider failed for NORAD {norad_id}: {e}")

    name = tle["name"]

    satrec = None

    try:
        from sgp4.api import Satrec  # noqa: PLC0415

        satrec = Satrec.twoline2rv(tle["line1"], tle["line2"])
    except Exception as e:
        raise ValueError(f"Invalid TLE for NORAD {norad_id}: {e}")

    elements = orbital_elements(satrec)

    now_position, now_velocity = propagate(satrec, fetched_at)

    from sgp4.api import jday  # noqa: PLC0415

    jd_now, fr_now = jday(
        fetched_at.year,
        fetched_at.month,
        fetched_at.day,
        fetched_at.hour,
        fetched_at.minute,
        fetched_at.second + fetched_at.microsecond / 1e6,
    )

    subpoint = subsatellite_point(now_position, jd_now + fr_now)

    speed_km_s = math.sqrt(sum(v**2 for v in now_velocity))

    epoch_dt = _epoch_datetime(satrec)

    age_hours = tle_age_hours(epoch_dt.isoformat(), fetched_at)

    confidence, confidence_detail = compute_confidence(
        epoch_dt.isoformat(), epoch_dt.isoformat(), fetched_at
    )

    sources.append(
        {
            "kind": "orbital_data",
            "source": "Configured orbital provider (CelesTrak primary)",
            "retrieved_at": fetched_at.isoformat(),
        }
    )

    # International designator parsed from TLE line 1 (cols 10-17).
    intl_desig = tle["line1"][9:17].strip()

    # ---------------------------------------------
    # 3. IDENTITY + TYPE
    # ---------------------------------------------

    curated = curated_lookup(norad_id)

    heuristic_type = infer_object_type(name)

    object_type = (
        curated.get("object_type") if curated and curated.get("object_type")
        else heuristic_type
    )

    identity = {
        "object_name": curated["name"] if curated else name,
        "norad_id": norad_id,
        "international_designator": intl_desig or (
            curated.get("international_designator") if curated else None
        ),
        "object_type": object_type,
    }

    # ---------------------------------------------
    # 4. MISSION INTELLIGENCE (layered)
    # ---------------------------------------------

    mission = None

    if curated:
        mission = {k: v for k, v in curated.items() if k != "object_type"}
        mission["_source"] = "Curated local registry"
        sources.append(
            {"kind": "mission_metadata", "source": "Curated local registry",
             "retrieved_at": fetched_at.isoformat()}
        )
    else:
        hint = constellation_hint(name)

        external = fetch_mission_metadata(norad_id)

        if external and external.get("available"):
            mission = external
            sources.append(
                {"kind": "mission_metadata", "source": external["provider"],
                 "retrieved_at": fetched_at.isoformat()}
            )
        elif hint:
            mission = {
                **hint,
                "_source": "Constellation family knowledge (name-based)",
            }
        elif object_type == "DEBRIS":
            mission = {
                "mission_description": None,
                "_debris_context": (
                    "This is tracked space debris. It has no independent "
                    "operational mission but remains relevant because it can "
                    "participate in close approach events with operational "
                    "spacecraft."
                ),
                "_source": "Derived from TLE naming convention",
            }
        elif object_type == "ROCKET BODY":
            mission = {
                "mission_description": None,
                "_rocket_body_context": (
                    "This is a launch vehicle stage left in orbit after a "
                    "launch. Its associated mission details are only shown "
                    "when verified metadata is available."
                ),
                "_source": "Derived from TLE naming convention",
            }
        else:
            mission = {
                "mission_description": None,
                "_unavailable_reason": (
                    "No verified mission metadata available for this object. "
                    "Configure a mission metadata provider to enrich profiles."
                ),
                "_source": "Not configured",
            }

    # ---------------------------------------------
    # 5. OPERATIONAL STATUS
    # ---------------------------------------------
    # Never guessed: curated public facts or external provider.

    status = "UNKNOWN"

    if curated and curated.get("operational_status"):
        status = curated["operational_status"]
    elif external and isinstance(external, dict) and external.get("available") \
            and external.get("statuses"):
        status = str(external["statuses"]).upper()

    status_info = {
        "status": status,
        "basis": (
            "Verified public record"
            if curated
            else ("External provider" if status != "UNKNOWN" else "Unverified — unknown")
        ),
    }

    # ---------------------------------------------
    # 6. END OF LIFE
    # ---------------------------------------------
    # Verified facts when curated; otherwise a clearly-labeled
    # heuristic lifetime estimate from the actual perigee.

    end_of_life = {
        "expected_reentry": (
            curated.get("expected_reentry") if curated else None
        ),
        "estimated_orbital_lifetime": None,
        "basis": None,
    }

    if not end_of_life["expected_reentry"]:
        lifetime = estimate_orbital_lifetime(
            elements.get("perigee_altitude_km")
        )

        end_of_life["estimated_orbital_lifetime"] = lifetime[
            "estimated_lifetime"
        ]
        end_of_life["basis"] = lifetime["basis"]
    else:
        end_of_life["basis"] = "Verified public record (curated registry)."

    # ---------------------------------------------
    # 7. CONJUNCTION CONTEXT (real DB events)
    # ---------------------------------------------

    conjunction_context = None

    if db is not None:
        conjunction_context = _conjunction_context(db, norad_id, fetched_at)

    profile = {
        "identity": identity,
        "mission": mission,
        "status": status_info,
        "end_of_life": end_of_life,
        "live_orbit": {
            **subpoint,
            "velocity_km_s": round(speed_km_s, 4),
            **elements,
            "tle_epoch": epoch_dt.isoformat(),
            "position_teme_km": [round(v, 3) for v in now_position],
            "computed_at": fetched_at.isoformat(),
        },
        "data_quality": {
            "tle_age_hours": round(age_hours, 2) if age_hours is not None else None,
            "freshness": freshness_label(age_hours),
            "confidence_score": confidence,
            "confidence_detail": confidence_detail,
            "last_orbital_update": epoch_dt.isoformat(),
            "orbital_data_source": "CelesTrak (primary) via cache chain",
        },
        "conjunction_context": conjunction_context,
        "sources": sources,
        "integrations": feature_flags(),
        "profile_generated_at": fetched_at.isoformat(),
    }

    if use_cache and db is not None:
        _write_cache(db, norad_id, profile, sources)

    return profile


# ==========================================
# CACHE + CONTEXT HELPERS
# ==========================================


def _epoch_datetime(satrec) -> datetime:
    """
    Version-tolerant Satrec epoch -> timezone-aware UTC datetime.
    JD 2440587.5 == 1970-01-01 00:00 UTC.
    Newer sgp4 exposes jdsatepochf; older builds only jdsatepoch.
    """

    from datetime import timedelta  # noqa: PLC0415

    fr = getattr(satrec, "jdsatepochf", 0.0)

    return datetime(1970, 1, 1, tzinfo=timezone.utc) + timedelta(
        days=(satrec.jdsatepoch + fr) - 2440587.5
    )


def _read_cache(db, norad_id: int):
    from backend.database.models import ObjectProfileCache  # noqa: PLC0415

    try:
        record = (
            db.query(ObjectProfileCache)
            .filter(ObjectProfileCache.norad_id == norad_id)
            .first()
        )

        if record is None:
            return None

        age = time.time() - record.fetched_at.timestamp()

        if age < PROFILE_TTL_SECONDS:
            profile = dict(record.profile)
            profile["cache"] = {"hit": True, "age_seconds": int(age)}
            return profile

        return None

    except Exception as e:
        print(f"[PROFILE] Cache read failed: {e}")
        return None


def _write_cache(db, norad_id: int, profile: dict, sources):
    from backend.database.models import ObjectProfileCache  # noqa: PLC0415

    try:
        record = (
            db.query(ObjectProfileCache)
            .filter(ObjectProfileCache.norad_id == norad_id)
            .first()
        )

        payload = {k: v for k, v in profile.items() if k != "cache"}

        if record is None:
            record = ObjectProfileCache(norad_id=norad_id, profile=payload,
                                        sources=sources)
            db.add(record)
        else:
            record.profile = payload
            record.sources = sources
            record.fetched_at = datetime.now(timezone.utc)

        db.commit()

    except Exception as e:
        db.rollback()
        print(f"[PROFILE] Cache write failed: {e}")


def _conjunction_context(db, norad_id: int, reference: datetime):
    from sqlalchemy import or_  # noqa: PLC0415

    from backend.database.models import Conjunction  # noqa: PLC0415

    try:
        upcoming = (
            db.query(Conjunction)
            .filter(
                or_(
                    Conjunction.satellite_a_norad_id == norad_id,
                    Conjunction.satellite_b_norad_id == norad_id,
                ),
                Conjunction.tca >= reference,
            )
            .order_by(Conjunction.tca.asc())
            .limit(5)
            .all()
        )

        def serialize(rec):
            other = (
                rec.satellite_b_norad_id
                if rec.satellite_a_norad_id == norad_id
                else rec.satellite_a_norad_id
            )

            return {
                "conjunction_id": rec.id,
                "other_norad_id": other,
                "tca": rec.tca.isoformat(),
                "minimum_distance_km": rec.minimum_distance_km,
                "risk_status": rec.risk_status,
                "risk_score": rec.risk_score,
            }

        if not upcoming:
            return {"upcoming_events": [], "note":
                    "No upcoming conjunctions recorded in this database."}

        nearest = upcoming[0]

        highest_risk = max(upcoming, key=lambda r: r.risk_score or -1)

        return {
            "upcoming_events": [serialize(r) for r in upcoming],
            "next_event": serialize(nearest),
            "highest_risk_event": serialize(highest_risk),
        }

    except Exception as e:
        print(f"[PROFILE] Conjunction context failed: {e}")
        return None
