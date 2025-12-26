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
    
    # Daily accumulation for averaging
    daily_temp_readings: list[float] = []
    daily_humidity_readings: list[float] = []
    daily_wind_readings: list[float] = []
    daily_solar_readings: list[float] = []
    daily_pressure_readings: list[float] = []
    
    # Track when we last recorded readings
    last_reading_time: datetime | None = None
    
    def __init__(self):
        """Initialize weather state with empty lists."""
        self.daily_temp_readings = []
        self.daily_humidity_readings = []
        self.daily_wind_readings = []
        self.daily_solar_readings = []
        self.daily_pressure_readings = []
    
    def record_reading(self):
        """Record current sensor values for daily averaging."""
        if self.temperature is not None:
            self.daily_temp_readings.append(self.temperature)
        if self.humidity is not None:
            self.daily_humidity_readings.append(self.humidity)
        if self.wind_speed is not None:
            self.daily_wind_readings.append(self.wind_speed)
        if self.solar_radiation is not None:
            self.daily_solar_readings.append(self.solar_radiation)
        if self.pressure is not None:
            self.daily_pressure_readings.append(self.pressure)
        self.last_reading_time = datetime.now()
    
    def get_daily_averages(self) -> dict:
        """Calculate and return daily averages."""
        return {
            'temp_avg': sum(self.daily_temp_readings) / len(self.daily_temp_readings) if self.daily_temp_readings else self.temperature,
            'humidity_avg': sum(self.daily_humidity_readings) / len(self.daily_humidity_readings) if self.daily_humidity_readings else self.humidity,
            'wind_avg': sum(self.daily_wind_readings) / len(self.daily_wind_readings) if self.daily_wind_readings else self.wind_speed,
            'solar_avg': sum(self.daily_solar_readings) / len(self.daily_solar_readings) if self.daily_solar_readings else self.solar_radiation,
            'pressure_avg': sum(self.daily_pressure_readings) / len(self.daily_pressure_readings) if self.daily_pressure_readings else self.pressure,
            'num_readings': len(self.daily_temp_readings),
        }
    
    def reset_daily_readings(self):
        """Clear daily accumulation after midnight ET calculation."""
        self.daily_temp_readings = []
        self.daily_humidity_readings = []
        self.daily_wind_readings = []
        self.daily_solar_readings = []
        self.daily_pressure_readings = []


class State:
    """Global state for Adaptive Irrigation integration."""

    zones: dict[str, ZoneState] = {}
    weather: WeatherState
    last_update: datetime | None = None

    def __init__(self):
        """Initialize state."""
        self.weather = WeatherState()
        self.zones = {}
