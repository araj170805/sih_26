def build_forecast_output(start_time, horizon_hours, step_minutes, objects, events):
    """
    Convert internal orbital results into a
    frontend/AI-friendly structure.
    """

    formatted_events = []

    for event in events:
        formatted_events.append(
            {
                "object_a": event["object_a"],
                "object_b": event["object_b"],
                "tca": event["tca"].isoformat(),
                "minimum_separation_km": round(event["minimum_distance_km"], 3),
                "coarse_tca": (
                    event["coarse_tca"].isoformat() if event.get("coarse_tca") else None
                ),
                "coarse_separation_km": round(event["coarse_distance_km"], 3),
                "status": event["status"],
            }
        )

    return {
        "forecast": {
            "start": start_time.isoformat(),
            "horizon_hours": horizon_hours,
            "step_minutes": step_minutes,
        },
        "objects": [obj["name"] for obj in objects],
        "object_count": len(objects),
        "events": formatted_events,
    }
