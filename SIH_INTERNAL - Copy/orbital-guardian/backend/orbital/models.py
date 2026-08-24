from dataclasses import dataclass
from datetime import datetime


@dataclass
class ForecastConfig:
    """
    Configuration for an orbital forecast.
    """

    horizon_hours: float = 24
    step_minutes: int = 1


@dataclass
class ConjunctionEvent:
    """
    Result of a close-approach analysis.
    """

    object_a: str
    object_b: str

    tca: datetime
    minimum_separation_km: float

    coarse_tca: datetime | None = None
    coarse_distance_km: float | None = None

    status: str = "SAFE"
