"""State management for Adaptive Irrigation integration."""

from datetime import datetime


class ZoneState:
    """State for an irrigation zone."""

    soil_moisture_balance: float = 0.0  # mm (0 = optimal, positive = excess, negative = deficit)
    last_rainfall: float = 0.0  # mm
    last_et: float = 0.0  # mm
    last_et_calculation: datetime | None = None
    last_midnight_update: datetime | None = None
    sprinkler_on_time: datetime | None = None
    total_sprinkler_runtime_today: float = 0.0  # seconds


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
