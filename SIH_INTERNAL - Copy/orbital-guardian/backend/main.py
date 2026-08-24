from datetime import datetime, timezone

from orbital.data_fetcher import fetch_tle
from orbital.output import build_forecast_output
from orbital.screening import screen_objects
from orbital.tle_parser import parse_tle

# ==========================================
# CONFIGURATION
# ==========================================

NORAD_IDS = [
    25544,  # ISS
    43013,  # NOAA-20
]

FORECAST_HOURS = 24
STEP_MINUTES = 1


# ==========================================
# FETCH OBJECTS
# ==========================================

print()
print("==========================================")
print("       ORBITAL GUARDIAN")
print("==========================================")

print()
print("Fetching current orbital data...")


objects = []

for norad_id in NORAD_IDS:
    tle = fetch_tle(norad_id)

    satellite = parse_tle(tle["name"], tle["line1"], tle["line2"])

    objects.append(satellite)

    print(f"Loaded: {satellite['name']}")


# ==========================================
# FORECAST START
# ==========================================

start_time = datetime.now(timezone.utc)


# ==========================================
# N-OBJECT SCREENING
# ==========================================

print()
print(f"Forecast: {FORECAST_HOURS} hours")

print(f"Resolution: {STEP_MINUTES} minute")

print(f"Objects: {len(objects)}")

print()

trajectories, events = screen_objects(
    objects, start_time, forecast_hours=FORECAST_HOURS, step_minutes=STEP_MINUTES
)


# ==========================================
# BUILD OUTPUT
# ==========================================

output = build_forecast_output(
    start_time, FORECAST_HOURS, STEP_MINUTES, objects, events
)


# ==========================================
# DISPLAY RESULTS
# ==========================================

print()
print("==========================================")
print("       CONJUNCTION RESULTS")
print("==========================================")

for event in output["events"]:
    print()
    print(f"{event['object_a']} ↔ {event['object_b']}")

    print(f"TCA: {event['tca']}")

    print(f"Minimum separation: {event['minimum_separation_km']} km")

    print(f"Status: {event['status']}")


print()
print("==========================================")
print("Pipeline completed successfully.")
print("==========================================")
