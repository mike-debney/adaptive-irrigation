"""The Adaptive Irrigation integration."""

from __future__ import annotations

from datetime import datetime, timedelta, time as dt_time
import logging

import pandas as pd

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_ON, Platform
from homeassistant.core import Event, HomeAssistant
from homeassistant.helpers.event import (
    EventStateChangedData,
    async_track_state_change_event,
    async_track_time_change,
)
from homeassistant.helpers.typing import ConfigType
from homeassistant.components import recorder
from homeassistant.components.recorder import history

from .config import Config, WeatherSensorConfig, ZoneConfig
from .const import DOMAIN
from .state import State, WeatherState, ZoneState

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.NUMBER, Platform.SENSOR]

# Store per-entry instances keyed by entry_id
CONFIGS: dict[str, Config] = {}
STATES: dict[str, State] = {}


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the Adaptive Irrigation component from YAML (not supported)."""
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Adaptive Irrigation from a config entry."""
    _LOGGER.info("Setting up Adaptive Irrigation from config entry: %s", entry.entry_id)

    try:
        # Create per-entry instances
        CONFIGS[entry.entry_id] = Config()
        STATES[entry.entry_id] = State()

        config = CONFIGS[entry.entry_id]
        state = STATES[entry.entry_id]

        # Parse configuration from config entry
        parse_config(entry, config)
        initialise_state(hass, config, state)

        # Track entity state changes
        entity_ids = [
            config.weather_sensors.temperature_entity,
            config.weather_sensors.humidity_entity,
            config.weather_sensors.precipitation_entity,
        ]

        if config.weather_sensors.wind_speed_entity:
            entity_ids.append(config.weather_sensors.wind_speed_entity)
        if config.weather_sensors.solar_radiation_entity:
            entity_ids.append(config.weather_sensors.solar_radiation_entity)
        if config.weather_sensors.pressure_entity:
            entity_ids.append(config.weather_sensors.pressure_entity)

        # Add sprinkler entities
        for zone_config in config.zones.values():
            entity_ids.append(zone_config.sprinkler_entity)

        async def state_change_listener(event: Event[EventStateChangedData]) -> None:
            """Handle state changes for weather sensors and sprinklers."""
            if event.event_type != "state_changed":
                return

            entity_id = event.data["entity_id"]
            new_state = event.data.get("new_state")
            old_state = event.data.get("old_state")

            if new_state is None:
                return

            # Weather sensor updates
            if entity_id == config.weather_sensors.temperature_entity:
                if new_state.state not in ("unknown", "unavailable"):
                    value = float(new_state.state)
                    if is_valid_temperature(value):
                        state.weather.temperature = value
                    else:
                        _LOGGER.warning("Invalid temperature: %.2f °C (ignored)", value)
            elif entity_id == config.weather_sensors.humidity_entity:
                if new_state.state not in ("unknown", "unavailable"):
                    value = float(new_state.state)
                    if is_valid_humidity(value):
                        state.weather.humidity = value
                    else:
                        _LOGGER.warning("Invalid humidity: %.2f%% (ignored)", value)
            elif entity_id == config.weather_sensors.precipitation_entity:
                if new_state.state not in ("unknown", "unavailable"):
                    new_precip = float(new_state.state)
                    
                    # Validate precipitation value
                    if not is_valid_precipitation(new_precip):
                        _LOGGER.warning("Invalid precipitation value: %.2f mm (ignored)", new_precip)
                        return
                    
                    old_precip = 0.0
                    if old_state and old_state.state not in ("unknown", "unavailable"):
                        old_precip = float(old_state.state)
                    
                    # If precipitation increased, add to all zones
                    precip_diff = new_precip - old_precip
                    if precip_diff > 0:
                        # Additional sanity check on the difference
                        if precip_diff > 200.0:
                            _LOGGER.warning("Excessive rainfall detected: %.2f mm (ignored, likely sensor error)", precip_diff)
                            return
                        
                        _LOGGER.info("Rainfall detected: %.2f mm", precip_diff)
                        for zone_id, zone_state in state.zones.items():
                            # Add rainfall to balance (moves toward excess/positive)
                            zone_state.soil_moisture_balance += precip_diff
                            zone_state.last_rainfall = precip_diff
                            update_zone_number(hass, entry.entry_id, zone_id, zone_state.soil_moisture_balance)
                    
                    state.weather.precipitation = new_precip

            elif (
                config.weather_sensors.wind_speed_entity
                and entity_id == config.weather_sensors.wind_speed_entity
            ):
                if new_state.state not in ("unknown", "unavailable"):
                    value = float(new_state.state)
                    if is_valid_wind_speed(value):
                        state.weather.wind_speed = value
                    else:
                        _LOGGER.warning("Invalid wind speed: %.2f km/h (ignored)", value)
            elif (
                config.weather_sensors.solar_radiation_entity
                and entity_id == config.weather_sensors.solar_radiation_entity
            ):
                if new_state.state not in ("unknown", "unavailable"):
                    value = float(new_state.state)
                    if is_valid_solar_radiation(value):
                        state.weather.solar_radiation = value
                    else:
                        _LOGGER.warning("Invalid solar radiation: %.2f W/m² (ignored)", value)
            elif (
                config.weather_sensors.pressure_entity
                and entity_id == config.weather_sensors.pressure_entity
            ):
                if new_state.state not in ("unknown", "unavailable"):
                    value = float(new_state.state)
                    if is_valid_pressure(value):
                        state.weather.pressure = value
                    else:
                        _LOGGER.warning("Invalid pressure: %.2f hPa (ignored)", value)

            # Sprinkler state changes
            for zone_id, zone_config in config.zones.items():
                if entity_id == zone_config.sprinkler_entity:
                    zone_state = state.zones[zone_id]
                    is_on = new_state.state == STATE_ON
                    was_on = old_state and old_state.state == STATE_ON if old_state else False

                    if is_on and not was_on:
                        # Sprinkler turned on
                        zone_state.sprinkler_on_time = datetime.now()
                        _LOGGER.info("Sprinkler turned on for zone %s", zone_config.name)
                    elif not is_on and was_on:
                        # Sprinkler turned off, calculate water added
                        if zone_state.sprinkler_on_time:
                            runtime_seconds = (
                                datetime.now() - zone_state.sprinkler_on_time
                            ).total_seconds()
                            zone_state.total_sprinkler_runtime_today += runtime_seconds
                            
                            # Calculate water added: (mm/hour) * (hours) = mm
                            runtime_hours = runtime_seconds / 3600
                            water_added = zone_config.precipitation_rate * runtime_hours
                            
                            # Add water to balance (moves toward excess/positive)
                            zone_state.soil_moisture_balance += water_added
                            
                            _LOGGER.info(
                                "Sprinkler off for zone %s. Runtime: %.2f min, Water added: %.2f mm",
                                zone_config.name,
                                runtime_seconds / 60,
                                water_added
                            )
                            
                            update_zone_number(hass, entry.entry_id, zone_id, zone_state.soil_moisture_balance)
                            zone_state.sprinkler_on_time = None

        # Subscribe to state changes
        entry.async_on_unload(
            async_track_state_change_event(hass, entity_ids, state_change_listener)
        )

        # Daily midnight ET calculation
        async def midnight_et_calculation(now: datetime) -> None:
            """Calculate and subtract ET at midnight."""
            _LOGGER.info("Running midnight ET calculation")
            await calculate_and_apply_et(hass, entry.entry_id)

        # Track midnight for ET calculation
        entry.async_on_unload(
            async_track_time_change(hass, midnight_et_calculation, hour=0, minute=0, second=0)
        )

        # Store entry in hass.data for platform access
        hass.data.setdefault(DOMAIN, {})
        hass.data[DOMAIN][entry.entry_id] = {
            "entry": entry,
            "config": config,
            "state": state,
        }

        # Register update listener for options changes
        entry.async_on_unload(entry.add_update_listener(async_reload_entry))

        # Forward entry setup to platforms
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

        # Register service for on-demand ET calculation
        async def handle_calculate_et(call):
            """Handle the calculate_et service call."""
            entry_id = call.data.get("entry_id")
            if entry_id:
                # Calculate for specific entry
                if entry_id in CONFIGS:
                    _LOGGER.info("Manual ET calculation triggered for entry %s", entry_id)
                    await calculate_and_apply_et(hass, entry_id)
                else:
                    _LOGGER.error("Entry ID %s not found", entry_id)
            else:
                # Calculate for all entries
                _LOGGER.info("Manual ET calculation triggered for all entries")
                for eid in CONFIGS:
                    await calculate_and_apply_et(hass, eid)

        hass.services.async_register(DOMAIN, "calculate_et", handle_calculate_et)

        _LOGGER.info("Adaptive Irrigation setup completed successfully")
        return True
        
    except Exception as e:
        _LOGGER.exception("Failed to set up Adaptive Irrigation: %s", e)
        # Clean up on failure
        CONFIGS.pop(entry.entry_id, None)
        STATES.pop(entry.entry_id, None)
        if DOMAIN in hass.data and entry.entry_id in hass.data[DOMAIN]:
            hass.data[DOMAIN].pop(entry.entry_id)
        raise


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload config entry when options change."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
        CONFIGS.pop(entry.entry_id, None)
        STATES.pop(entry.entry_id, None)
        
        # Unregister service if this is the last entry
        if not CONFIGS and hass.services.has_service(DOMAIN, "calculate_et"):
            hass.services.async_remove(DOMAIN, "calculate_et")

    return unload_ok


def parse_config(entry: ConfigEntry, config: Config) -> None:
    """Parse configuration from config entry."""
    config_data = {**entry.data, **entry.options}
    
    # Weather sensors
    weather_config = WeatherSensorConfig()
    weather_config.temperature_entity = config_data.get("temperature_entity")
    weather_config.humidity_entity = config_data.get("humidity_entity")
    weather_config.precipitation_entity = config_data.get("precipitation_entity")
    weather_config.wind_speed_entity = config_data.get("wind_speed_entity")
    weather_config.solar_radiation_entity = config_data.get("solar_radiation_entity")
    weather_config.pressure_entity = config_data.get("pressure_entity")
    weather_config.latitude = config_data.get("latitude", 0.0)
    weather_config.longitude = config_data.get("longitude", 0.0)
    weather_config.elevation = config_data.get("elevation", 0.0)
    config.weather_sensors = weather_config
    
    # Auto-select ET method based on available sensors
    if weather_config.wind_speed_entity and weather_config.solar_radiation_entity:
        # Penman-Monteith: most accurate, requires wind and solar
        config.et_method = "penman_monteith"
        _LOGGER.info("Using Penman-Monteith ET method (wind & solar available)")
    elif weather_config.solar_radiation_entity:
        # Priestley-Taylor: requires solar radiation
        config.et_method = "priestley_taylor"
        _LOGGER.info("Using Priestley-Taylor ET method (solar available)")
    else:
        # Hargreaves: simplest, requires only temperature
        config.et_method = "hargreaves"
        _LOGGER.info("Using Hargreaves ET method (minimal sensors)")
    
    # Zones
    zones_data = config_data.get("zones", [])
    for idx, zone_data in enumerate(zones_data):
        zone_id = f"zone_{idx}"
        zone_config = ZoneConfig()
        zone_config.name = zone_data.get("name", f"Zone {idx + 1}")
        zone_config.zone_id = zone_id
        zone_config.sprinkler_entity = zone_data.get("sprinkler_entity")
        zone_config.precipitation_rate = zone_data.get("precipitation_rate", 10.0)
        zone_config.crop_coefficient = zone_data.get("crop_coefficient", 1.0)
        config.zones[zone_id] = zone_config


def initialise_state(hass: HomeAssistant, config: Config, state: State) -> None:
    """Initialize state from current entity values."""
    # Initialize weather state
    temp_state = hass.states.get(config.weather_sensors.temperature_entity)
    if temp_state and temp_state.state not in ("unknown", "unavailable"):
        value = float(temp_state.state)
        if is_valid_temperature(value):
            state.weather.temperature = value
        else:
            _LOGGER.warning("Invalid initial temperature: %.2f °C", value)
    
    humidity_state = hass.states.get(config.weather_sensors.humidity_entity)
    if humidity_state and humidity_state.state not in ("unknown", "unavailable"):
        value = float(humidity_state.state)
        if is_valid_humidity(value):
            state.weather.humidity = value
        else:
            _LOGGER.warning("Invalid initial humidity: %.2f%%", value)
    
    precip_state = hass.states.get(config.weather_sensors.precipitation_entity)
    if precip_state and precip_state.state not in ("unknown", "unavailable"):
        value = float(precip_state.state)
        if is_valid_precipitation(value):
            state.weather.precipitation = value
        else:
            _LOGGER.warning("Invalid initial precipitation: %.2f mm", value)
    
    if config.weather_sensors.wind_speed_entity:
        wind_state = hass.states.get(config.weather_sensors.wind_speed_entity)
        if wind_state and wind_state.state not in ("unknown", "unavailable"):
            value = float(wind_state.state)
            if is_valid_wind_speed(value):
                state.weather.wind_speed = value
            else:
                _LOGGER.warning("Invalid initial wind speed: %.2f km/h", value)
    
    if config.weather_sensors.solar_radiation_entity:
        solar_state = hass.states.get(config.weather_sensors.solar_radiation_entity)
        if solar_state and solar_state.state not in ("unknown", "unavailable"):
            value = float(solar_state.state)
            if is_valid_solar_radiation(value):
                state.weather.solar_radiation = value
            else:
                _LOGGER.warning("Invalid initial solar radiation: %.2f W/m²", value)
    
    if config.weather_sensors.pressure_entity:
        pressure_state = hass.states.get(config.weather_sensors.pressure_entity)
        if pressure_state and pressure_state.state not in ("unknown", "unavailable"):
            value = float(pressure_state.state)
            if is_valid_pressure(value):
                state.weather.pressure = value
            else:
                _LOGGER.warning("Invalid initial pressure: %.2f hPa", value)
    
    # Initialize zone states
    for zone_id, zone_config in config.zones.items():
        zone_state = ZoneState()
        zone_state.soil_moisture_balance = 0.0  # Start at optimal
        state.zones[zone_id] = zone_state


def is_valid_temperature(value: float) -> bool:
    """Check if temperature value is within reasonable bounds."""
    return -50.0 <= value <= 60.0


def is_valid_humidity(value: float) -> bool:
    """Check if humidity value is within valid range."""
    return 0.0 <= value <= 100.0


def is_valid_wind_speed(value: float) -> bool:
    """Check if wind speed is within reasonable bounds."""
    return 0.0 <= value <= 200.0  # km/h (reasonable maximum for surface weather)


def is_valid_solar_radiation(value: float) -> bool:
    """Check if solar radiation is within reasonable bounds."""
    return 0.0 <= value <= 1500.0  # W/m² (max solar constant ~1361 W/m² plus atmosphere)


def is_valid_pressure(value: float) -> bool:
    """Check if pressure is within reasonable atmospheric range."""
    return 800.0 <= value <= 1100.0  # hPa (covers extreme weather conditions)


def is_valid_precipitation(value: float) -> bool:
    """Check if precipitation is within reasonable bounds."""
    return 0.0 <= value <= 500.0  # mm/day (extreme rainfall, but possible)


async def get_historical_weather_data(
    hass: HomeAssistant, 
    entity_id: str, 
    start_time: datetime, 
    end_time: datetime,
    validator=None
) -> list[float]:
    """Get historical sensor data from the database with optional validation."""
    states = await recorder.get_instance(hass).async_add_executor_job(
        history.state_changes_during_period,
        hass,
        start_time,
        end_time,
        entity_id,
        True,  # include_start_time_state
        True,  # significant_changes_only
        1000,  # minimal_response - limit number of results
    )
    
    if not states or entity_id not in states:
        return []
    
    values = []
    filtered_count = 0
    for state in states[entity_id]:
        if state.state not in ("unknown", "unavailable", "None"):
            try:
                value = float(state.state)
                # Apply validation if provided
                if validator is None or validator(value):
                    values.append(value)
                else:
                    filtered_count += 1
                    _LOGGER.debug("Filtered invalid sensor value: %.2f from %s", value, entity_id)
            except (ValueError, TypeError):
                continue
    
    if filtered_count > 0:
        _LOGGER.info("Filtered %d invalid readings from %s", filtered_count, entity_id)
    
    return values


async def calculate_and_apply_et(hass: HomeAssistant, entry_id: str) -> None:
    """Calculate ET using pyet and subtract from soil moisture."""
    config = CONFIGS[entry_id]
    state = STATES[entry_id]
    
    try:
        import pyet
    except ImportError:
        _LOGGER.error("pyet package not installed. Cannot calculate ET.")
        return
    
    # Query the previous day's data from database
    end_time = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    start_time = end_time - timedelta(days=1)
    
    _LOGGER.info("Fetching weather data from %s to %s", start_time, end_time)
    
    # Fetch historical data for all sensors with validation
    temp_data = await get_historical_weather_data(
        hass, config.weather_sensors.temperature_entity, start_time, end_time, is_valid_temperature
    )
    humidity_data = await get_historical_weather_data(
        hass, config.weather_sensors.humidity_entity, start_time, end_time, is_valid_humidity
    )
    
    if not temp_data or not humidity_data:
        _LOGGER.warning("Missing required weather data for ET calculation")
        return
    
    _LOGGER.info("Retrieved %d temperature and %d humidity readings from database", 
                 len(temp_data), len(humidity_data))
    
    # Calculate averages (temperature must be in Celsius for pyet)
    temp_avg = sum(temp_data) / len(temp_data)
    humidity_avg = sum(humidity_data) / len(humidity_data)
    
    # Create dataframe for pyet (requires daily data)
    date = (datetime.now() - timedelta(days=1)).date()
    
    df = pd.DataFrame({
        'tmean': [temp_avg],
        'rh': [humidity_avg],
    }, index=pd.DatetimeIndex([pd.Timestamp(date)]))
    
    # Add optional parameters if available
    if config.weather_sensors.wind_speed_entity:
        wind_data = await get_historical_weather_data(
            hass, config.weather_sensors.wind_speed_entity, start_time, end_time, is_valid_wind_speed
        )
        if wind_data:
            # Convert km/h to m/s (pyet expects m/s)
            # km/h ÷ 3.6 = m/s
            wind_avg_kmh = sum(wind_data) / len(wind_data)
            wind_avg_ms = wind_avg_kmh / 3.6
            df['wind'] = [wind_avg_ms]
            _LOGGER.debug("Wind speed average: %.2f km/h (%.2f m/s) from %d readings", 
                         wind_avg_kmh, wind_avg_ms, len(wind_data))
    
    if config.weather_sensors.solar_radiation_entity:
        solar_data = await get_historical_weather_data(
            hass, config.weather_sensors.solar_radiation_entity, start_time, end_time, is_valid_solar_radiation
        )
        if solar_data:
            # Convert W/m² (average) to MJ/m²/day (pyet expects MJ/m²/day)
            # W/m² × 0.0864 = MJ/m²/day
            solar_avg_wm2 = sum(solar_data) / len(solar_data)
            solar_avg_mj = solar_avg_wm2 * 0.0864
            df['rs'] = [solar_avg_mj]
            _LOGGER.debug("Solar radiation average: %.2f W/m² (%.2f MJ/m²/day) from %d readings", 
                         solar_avg_wm2, solar_avg_mj, len(solar_data))
    
    if config.weather_sensors.pressure_entity:
        pressure_data = await get_historical_weather_data(
            hass, config.weather_sensors.pressure_entity, start_time, end_time, is_valid_pressure
        )
        if pressure_data:
            # Convert hPa to kPa (pyet expects kPa)
            pressure_avg_hpa = sum(pressure_data) / len(pressure_data)
            pressure_avg_kpa = pressure_avg_hpa / 10.0
            df['pressure'] = [pressure_avg_kpa]
            _LOGGER.debug("Pressure average: %.2f hPa (%.2f kPa) from %d readings", 
                         pressure_avg_hpa, pressure_avg_kpa, len(pressure_data))
    
    try:
        # Calculate ET based on selected method
        lat = config.weather_sensors.latitude
        elevation = config.weather_sensors.elevation
        
        if config.et_method == "penman_monteith":
            # Requires more data
            if 'wind' in df.columns and 'rs' in df.columns:
                et0 = pyet.pm_fao56(
                    df['tmean'], 
                    df['wind'], 
                    df['rs'],
                    df['rh'],
                    elevation=elevation,
                    lat=lat
                )
            else:
                _LOGGER.warning("Insufficient data for Penman-Monteith, using Hargreaves")
                et0 = pyet.hargreaves(df['tmean'], lat=lat)
        elif config.et_method == "priestley_taylor":
            if 'rs' in df.columns:
                et0 = pyet.priestley_taylor(df['tmean'], df['rs'], elevation=elevation, lat=lat)
            else:
                _LOGGER.warning("Insufficient data for Priestley-Taylor, using Hargreaves")
                et0 = pyet.hargreaves(df['tmean'], lat=lat)
        else:  # hargreaves (default/fallback)
            et0 = pyet.hargreaves(df['tmean'], lat=lat)
        
        # Get the ET value (in mm)
        et_mm = float(et0.iloc[0]) if not et0.empty else 0.0
        
        _LOGGER.debug("Calculated ET0: %.2f mm/day", et_mm)
        
        # Apply ET to all zones with crop coefficient
        for zone_id, zone_config in config.zones.items():
            zone_state = state.zones[zone_id]
            
            # Apply crop coefficient
            et_actual = et_mm * zone_config.crop_coefficient
            
            # Subtract ET from balance (moves toward deficit/negative)
            zone_state.soil_moisture_balance -= et_actual
            zone_state.last_et = et_actual
            zone_state.last_et_calculation = datetime.now()
            zone_state.total_sprinkler_runtime_today = 0.0  # Reset daily counter
            
            _LOGGER.debug(
                "Zone %s: ET=%.2f mm, New balance=%.2f mm",
                zone_config.name,
                et_actual,
                zone_state.soil_moisture_balance
            )
            
            # Update number entity
            update_zone_number(hass, entry_id, zone_id, zone_state.soil_moisture_balance)
    
    except Exception as e:
        _LOGGER.error("Error calculating ET: %s", e)


def update_zone_number(hass: HomeAssistant, entry_id: str, zone_id: str, balance: float) -> None:
    """Update the soil moisture balance number for a zone."""
    if DOMAIN not in hass.data or entry_id not in hass.data[DOMAIN]:
        return
    
    entities = hass.data[DOMAIN][entry_id].get("entities", {})
    number_key = f"soil_moisture_balance_{zone_id}"
    
    if number_key in entities:
        number = entities[number_key]
        number.update_value(balance)
