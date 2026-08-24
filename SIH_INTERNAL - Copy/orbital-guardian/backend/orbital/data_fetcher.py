import json
import time
from pathlib import Path

import requests

CELESTRAK_URL = "https://celestrak.org/NORAD/elements/gp.php"

FALLBACK_URL = "https://tle.ivanstanojevic.me/api/tle"

# Disk cache so TLEs survive restarts and
# temporary upstream outages / rate limits.
CACHE_FILE = Path(__file__).resolve().parent.parent / "data" / "tle_cache.json"

CACHE_TTL_SECONDS = 4 * 3600

_memory_cache = {}

_disk_cache_loaded = False


def _load_disk_cache():
    global _disk_cache_loaded

    if _disk_cache_loaded:
        return

    _disk_cache_loaded = True

    try:
        if CACHE_FILE.exists():
            _memory_cache.update(json.loads(CACHE_FILE.read_text()))
    except Exception as e:
        print(f"[TLE CACHE] Could not read disk cache: {e}")


def _store_in_cache(norad_id, tle):
    _load_disk_cache()

    _memory_cache[str(norad_id)] = {"fetched_at": time.time(), "tle": tle}

    try:
        CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        CACHE_FILE.write_text(json.dumps(_memory_cache))
    except Exception as e:
        print(f"[TLE CACHE] Could not write disk cache: {e}")


def _get_cached_tle(norad_id):
    _load_disk_cache()

    return _memory_cache.get(str(norad_id))


def _fetch_celestrak(norad_id):
    params = {"CATNR": norad_id, "FORMAT": "TLE"}

    response = requests.get(CELESTRAK_URL, params=params, timeout=15)

    if response.status_code == 404:
        # CelesTrak signals unknown NORAD IDs
        # with an empty 404 response.
        raise ValueError(f"No TLE found for NORAD ID {norad_id}")

    response.raise_for_status()

    lines = [line.strip() for line in response.text.splitlines() if line.strip()]

    if len(lines) < 3:
        raise ValueError(f"No valid TLE returned for NORAD ID {norad_id}")

    return {"name": lines[0], "line1": lines[1], "line2": lines[2]}


def _fetch_fallback(norad_id):
    """
    Secondary TLE source used when CelesTrak is
    unavailable or rate-limits us.
    """

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 Chrome/126.0 Safari/537.36"
        ),
        "Accept": "application/json",
    }

    response = requests.get(f"{FALLBACK_URL}/{norad_id}", timeout=15, headers=headers)

    if response.status_code != 200:
        raise RuntimeError(f"Fallback source returned HTTP {response.status_code}")

    data = response.json()

    if not data.get("line1") or not data.get("line2"):
        raise RuntimeError("Fallback source returned incomplete TLE data")

    return {
        "name": data.get("name", f"NORAD {norad_id}"),
        "line1": data["line1"],
        "line2": data["line2"],
    }


def fetch_tle(norad_id):
    """
    Fetch the latest TLE with layered resilience:

        1. Fresh in-memory/disk cache (< 4 h old)
        2. CelesTrak (primary)
        3. Fallback TLE API
        4. Stale cache entry (better than failing)

    Raises ValueError only when the NORAD ID is
    genuinely unknown to the primary source.
    """

    cached = _get_cached_tle(norad_id)

    # 1. Fresh cache — no network needed.
    if cached and time.time() - cached["fetched_at"] < CACHE_TTL_SECONDS:
        return cached["tle"]

    # 2. Primary source.
    try:
        tle = _fetch_celestrak(norad_id)
        _store_in_cache(norad_id, tle)
        return tle
    except ValueError:
        # Unknown NORAD ID — do not mask this.
        raise
    except Exception:
        pass  # Blocked / offline — try fallbacks.

    # 3. Fallback source.
    try:
        tle = _fetch_fallback(norad_id)
        _store_in_cache(norad_id, tle)
        return tle
    except Exception:
        pass

    # 4. Stale cache.
    if cached:
        print(f"[TLE CACHE] Serving stale TLE for NORAD {norad_id}")
        return cached["tle"]

    raise RuntimeError(
        f"All TLE sources failed for NORAD {norad_id}. "
        "CelesTrak may be rate-limiting this IP."
    )


# Catalog groups exposed for live tracking.
# Kept deliberately small — the prototype
# screens a limited range of objects.
CATALOG_GROUPS = {
    "stations": "International Space Station + Chinese station",
    "visual": "Bright / easily observed objects (~160)",
    "starlink": "Starlink constellation (large)",
    "active": "All active satellites (very large)",
}


def fetch_catalog(group="stations", limit=100):
    """
    Fetch a batch of TLEs for live tracking.

    Uses CelesTrak GROUP queries and returns
    up to `limit` parsed records:
        [{norad_id, name, line1, line2}, ...]

    This is how the prototype stays within a
    limited, controlled object range instead
    of screening the full catalog.
    """

    if group not in CATALOG_GROUPS:
        raise ValueError(
            f"Unknown catalog group '{group}'. Allowed: {', '.join(CATALOG_GROUPS)}"
        )

    params = {"GROUP": group, "FORMAT": "TLE"}

    response = requests.get(CELESTRAK_URL, params=params, timeout=30)

    response.raise_for_status()

    lines = [line.strip() for line in response.text.splitlines() if line.strip()]

    if len(lines) < 3:
        raise ValueError(f"No catalog data returned for group '{group}'")

    objects = []

    # Records arrive as 3-line blocks:
    #   name
    #   TLE line 1
    #   TLE line 2
    for index in range(0, len(lines) - 2, 3):
        name = lines[index]
        line1 = lines[index + 1]
        line2 = lines[index + 2]

        try:
            norad_id = int(line2.split()[1])

        except (IndexError, ValueError):
            continue

        objects.append(
            {"norad_id": norad_id, "name": name, "line1": line1, "line2": line2}
        )

        if len(objects) >= limit:
            break

    return objects
