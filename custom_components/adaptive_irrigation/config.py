"""Configuration classes for Adaptive Irrigation integration."""


class WeatherSensorConfig:
    """Configuration for weather sensors."""

    temperature_entity: str
    humidity_entity: str
    wind_speed_entity: str | None = None
    solar_radiation_entity: str | None = None
    pressure_entity: str | None = None
    precipitation_entity: str
    latitude: float
    longitude: float
    elevation: float


class ZoneConfig:
    """Configuration for an irrigation zone."""

    name: str
    zone_id: str
    sprinkler_entity: str
    precipitation_rate: float  # mm/hour
    crop_coefficient: float = 1.0  # Kc for ET adjustment
    max_runtime: int = 3600  # seconds
    min_runtime: int = 60  # seconds
    minimum_interval: int = 3600  # seconds - minimum time between irrigation cycles
    max_balance: float = 5.0  # mm - don't run if balance is above this
    min_balance: float = -20.0  # mm - don't run if balance is below this (too dry for effective irrigation)


class Config:
    """Configuration for Adaptive Irrigation integration."""

    weather_sensors: WeatherSensorConfig
    zones: dict[str, ZoneConfig] = {}
    et_method: str = "penman_monteith"
