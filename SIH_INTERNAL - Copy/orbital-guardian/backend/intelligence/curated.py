"""
Curated local knowledge for well-known objects.

Every entry is factual and static (mission-level metadata
that does not change). Operational status is NEVER asserted
here unless it is public, stable knowledge — otherwise it is
left UNKNOWN and resolved by the status resolver.

This registry exists so the platform shows real mission
context for famous objects even when no external metadata
provider is configured.
"""

CURATED_OBJECTS: dict[int, dict] = {
    25544: {
        "name": "ISS (ZARYA)",
        "international_designator": "1998-067A",
        "object_type": "PAYLOAD",
        "mission_name": "International Space Station",
        "mission_description": (
            "A habitable modular space station and multinational "
            "microgravity laboratory operated by NASA, Roscosmos, ESA, "
            "JAXA and CSA."
        ),
        "mission_purpose": (
            "Sent to space to serve as a permanently crewed laboratory "
            "for biology, physics, medicine and technology experiments "
            "in microgravity, and as a testbed for long-duration "
            "human spaceflight."
        ),
        "mission_category": "Human Spaceflight",
        "operator": "NASA / Roscosmos / ESA / JAXA / CSA",
        "country": "Multinational",
        "launch_vehicle": "Proton-K (Zarya module)",
        "launch_date": "1998-11-20",
        "launch_site": "Baikonur Cosmodrome, Kazakhstan",
        "operational_status": "OPERATIONAL",
        "expected_reentry": (
            "Early-to-mid 2030s (planned controlled deorbit via NASA's "
            "US Deorbit Vehicle; station operations approved through ~2030)."
        ),
    },
    48274: {
        "name": "CSS (TIANHE)",
        "international_designator": "2021-035A",
        "object_type": "PAYLOAD",
        "mission_name": "Tiangong Space Station",
        "mission_description": (
            "Core module of China's modular space station, hosting "
            "crewed missions and scientific experiments."
        ),
        "mission_purpose": (
            "Sent to space as the living-quarters and command core of "
            "China's permanent space station programme."
        ),
        "mission_category": "Human Spaceflight",
        "operator": "China Manned Space Agency",
        "country": "China",
        "launch_vehicle": "Long March 5B",
        "launch_date": "2021-04-29",
        "launch_site": "Wenchang Spacecraft Launch Site, China",
        "operational_status": "OPERATIONAL",
        "expected_reentry": (
            "None planned — actively serviced station with station-keeping "
            "maneuvers for the foreseeable future."
        ),
    },
    20580: {
        "name": "HST",
        "international_designator": "1990-037B",
        "object_type": "PAYLOAD",
        "mission_name": "Hubble Space Telescope",
        "mission_description": (
            "NASA/ESA space telescope observing the universe across "
            "visible, ultraviolet and near-infrared wavelengths."
        ),
        "mission_purpose": (
            "Sent to space to observe the universe above Earth's "
            "atmosphere, free from atmospheric distortion, producing "
            "three decades of landmark astronomy."
        ),
        "mission_category": "Scientific Research",
        "operator": "NASA / ESA",
        "country": "United States / Europe",
        "launch_vehicle": "Space Shuttle Discovery (STS-31)",
        "launch_date": "1990-04-24",
        "launch_site": "Kennedy Space Center, United States",
        "operational_status": "OPERATIONAL",
        "expected_reentry": (
            "Projected mid-2030s without intervention (orbit decays "
            "gradually; NASA has discussed a reboost mission)."
        ),
    },
    28654: {
        "name": "NOAA 18",
        "international_designator": "2005-018A",
        "object_type": "PAYLOAD",
        "mission_name": "NOAA POES Series",
        "mission_description": (
            "Polar-orbiting weather satellite providing global meteorological "
            "and environmental sensing data (POES programme)."
        ),
        "mission_purpose": (
            "Sent to space to deliver global weather imagery, atmospheric "
            "sounding and search-and-rescue relay from polar orbit."
        ),
        "mission_category": "Earth Observation",
        "operator": "NOAA",
        "country": "United States",
        "launch_vehicle": "Boeing Delta II",
        "launch_date": "2005-05-20",
        "launch_site": "Vandenberg SFB, United States",
        # NOAA 18 was decommissioned from primary service — publicly known.
        "operational_status": "NON-OPERATIONAL",
    },
}

# Constellation families recognised by name prefix.
CONSTELLATION_HINTS = {
    "STARLINK": {
        "mission_category": "Communication",
        "operator": "SpaceX",
        "country": "United States",
        "mission_description": (
            "SpaceX broadband internet constellation in low Earth orbit. "
            "Individual satellites are interchangeable units of the fleet."
        ),
        "mission_name": "Starlink",
    },
    "ONEWEB": {
        "mission_category": "Communication",
        "operator": "Eutelsat OneWeb",
        "country": "United Kingdom / France",
        "mission_description": (
            "Low Earth orbit broadband communications constellation."
        ),
        "mission_name": "OneWeb",
    },
    "COSMOS": {
        "mission_category": "Other",
        "operator": "Unknown (Russian Cosmos programme)",
        "country": "Russia",
        "mission_description": None,
        "mission_name": "Cosmos programme",
    },
}


def lookup(norad_id: int) -> dict | None:
    return CURATED_OBJECTS.get(norad_id)


def constellation_hint(name: str) -> dict | None:
    upper = str(name).upper()

    for prefix, meta in CONSTELLATION_HINTS.items():
        if upper.startswith(prefix):
            return meta

    return None
