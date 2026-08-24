from itertools import combinations

from .conjunction import find_closest_approach


def screen_objects(objects, start_time, forecast_hours=24, step_minutes=1):
    """
    Generate trajectories for multiple objects
    and evaluate every unique object pair.
    """

    trajectories = {}

    # =========================================
    # 1. Generate trajectories
    # =========================================

    from .trajectory import generate_trajectory

    for obj in objects:
        print(f"Generating trajectory: {obj['name']}")

        trajectories[obj["name"]] = generate_trajectory(
            obj["satellite"],
            start_time,
            hours=forecast_hours,
            step_minutes=step_minutes,
        )

    # =========================================
    # 2. Compare unique pairs
    # =========================================

    events = []

    for object_a, object_b in combinations(objects, 2):
        name_a = object_a["name"]
        name_b = object_b["name"]

        print(f"Analyzing: {name_a} ↔ {name_b}")

        result = find_closest_approach(
            trajectories[name_a],
            trajectories[name_b],
            object_a["satellite"],
            object_b["satellite"],
        )

        result["object_a"] = name_a
        result["object_b"] = name_b

        events.append(result)

    return trajectories, events
