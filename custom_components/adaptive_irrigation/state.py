"""State management for Adaptive Irrigation integration."""

from datetime import datetime


class ZoneCalculatedValues:
    """Pre-calculated runtime values for a zone.
    
    These values are computed centrally by the coordinator and
    consumed by entities for display/persistence.
    """
    
    effective_deficit_mm: float = 0.0  # Deficit after accounting for forecast rain
    required_runtime_seconds: float = 0.0  # Raw runtime needed to cover deficit
    clamped_runtime_seconds: float = 0.0  # Runtime clamped to min/max limits
    forecast_rain_mm: float = 0.0  # Amount of forecasted rain accounted for
    can_run: bool = False  # Whether the zone should run
    reason: str = ""  # Human-readable reason for can_run status


class ZoneState:
    """State for an irrigation zone."""

    soil_moisture_balance: float = 0.0  # mm (0 = optimal, positive = excess, negative = deficit)
    last_rainfall: float = 0.0  # mm
    last_et: float = 0.0  # mm
    last_et_calculation: datetime | None = None
    last_midnight_update: datetime | None = None
    sprinkler_on_time: datetime | None = None
    sprinkler_off_time: datetime | None = None  # Track when valve was last turned off
    total_sprinkler_runtime_today: float = 0.0  # seconds
    
    # Pre-calculated values (updated by coordinator)
    calculated: ZoneCalculatedValues
    
    def __init__(self):
        """Initialize zone state."""
        self.calculated = ZoneCalculatedValues()


class WeatherState:
    """State for weather sensor data."""

    # Current/latest values
    temperature: float | None = None
    humidity: float | None = None
    wind_speed: float | None = None
    solar_radiation: float | None = None
    pressure: float | None = None
    precipitation: float = 0.0


class State:
    """Global state for Adaptive Irrigation integration."""

    zones: dict[str, ZoneState] = {}
    weather: WeatherState
    last_update: datetime | None = None

    def __init__(self):
        """Initialize state."""
        self.weather = WeatherState()
        self.zones = {}
