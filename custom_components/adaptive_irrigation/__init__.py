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
    async_track_time_interval,
)
from homeassistant.helpers.typing import ConfigType

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
                    state.weather.temperature = float(new_state.state)
            elif entity_id == config.weather_sensors.humidity_entity:
                if new_state.state not in ("unknown", "unavailable"):
                    state.weather.humidity = float(new_state.state)
            elif entity_id == config.weather_sensors.precipitation_entity:
                if new_state.state not in ("unknown", "unavailable"):
                    new_precip = float(new_state.state)
                    old_precip = 0.0
                    if old_state and old_state.state not in ("unknown", "unavailable"):
                        old_precip = float(old_state.state)
                    
                    # If precipitation increased, add to all zones
                    precip_diff = new_precip - old_precip
                    if precip_diff > 0:
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
                    state.weather.wind_speed = float(new_state.state)
            elif (
                config.weather_sensors.solar_radiation_entity
                and entity_id == config.weather_sensors.solar_radiation_entity
            ):
                if new_state.state not in ("unknown", "unavailable"):
                    state.weather.solar_radiation = float(new_state.state)
            elif (
                config.weather_sensors.pressure_entity
                and entity_id == config.weather_sensors.pressure_entity
            ):
                if new_state.state not in ("unknown", "unavailable"):
                    state.weather.pressure = float(new_state.state)

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

        # Record weather readings every 15 minutes for daily averaging
        async def record_weather_reading(now: datetime) -> None:
            """Record current weather sensor values for daily averaging."""
            state.weather.record_reading()
            _LOGGER.debug("Recorded weather reading: %d samples today", 
                         len(state.weather.daily_temp_readings))

        # Track every 15 minutes for weather sampling
        entry.async_on_unload(
            async_track_time_interval(hass, record_weather_reading, timedelta(minutes=15))
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
        state.weather.temperature = float(temp_state.state)
    
    humidity_state = hass.states.get(config.weather_sensors.humidity_entity)
    if humidity_state and humidity_state.state not in ("unknown", "unavailable"):
        state.weather.humidity = float(humidity_state.state)
    
    precip_state = hass.states.get(config.weather_sensors.precipitation_entity)
    if precip_state and precip_state.state not in ("unknown", "unavailable"):
        state.weather.precipitation = float(precip_state.state)
    
    if config.weather_sensors.wind_speed_entity:
        wind_state = hass.states.get(config.weather_sensors.wind_speed_entity)
        if wind_state and wind_state.state not in ("unknown", "unavailable"):
            state.weather.wind_speed = float(wind_state.state)
    
    if config.weather_sensors.solar_radiation_entity:
        solar_state = hass.states.get(config.weather_sensors.solar_radiation_entity)
        if solar_state and solar_state.state not in ("unknown", "unavailable"):
            state.weather.solar_radiation = float(solar_state.state)
    
    if config.weather_sensors.pressure_entity:
        pressure_state = hass.states.get(config.weather_sensors.pressure_entity)
        if pressure_state and pressure_state.state not in ("unknown", "unavailable"):
            state.weather.pressure = float(pressure_state.state)
    
    # Initialize zone states
    for zone_id, zone_config in config.zones.items():
        zone_state = ZoneState()
        zone_state.soil_moisture_balance = 0.0  # Start at optimal
        state.zones[zone_id] = zone_state


async def calculate_and_apply_et(hass: HomeAssistant, entry_id: str) -> None:
    """Calculate ET using pyet and subtract from soil moisture."""
    config = CONFIGS[entry_id]
    state = STATES[entry_id]
    
    try:
        import pyet
    except ImportError:
        _LOGGER.error("pyet package not installed. Cannot calculate ET.")
        return
    
    # Get daily averages
    daily_avg = state.weather.get_daily_averages()
    
    # Check if we have required weather data
    if daily_avg['temp_avg'] is None or daily_avg['humidity_avg'] is None:
        _LOGGER.warning("Missing required weather data for ET calculation")
        return
    
    _LOGGER.info("Calculating ET with %d weather samples from the day", daily_avg['num_readings'])
    
    # Create dataframe for pyet (requires daily data)
    # For midnight calculation, we use the previous day's average/values
    date = datetime.now().date() - timedelta(days=1)
    
    # Create simple dataframe with one day of data using daily averages
    df = pd.DataFrame({
        'tmean': [daily_avg['temp_avg']],
        'rh': [daily_avg['humidity_avg']],
    }, index=pd.DatetimeIndex([pd.Timestamp(date)]))
    
    # Add optional parameters if available
    if daily_avg['wind_avg'] is not None:
        df['wind'] = [daily_avg['wind_avg']]
    
    if daily_avg['solar_avg'] is not None:
        df['rs'] = [daily_avg['solar_avg']]
    
    if daily_avg['pressure_avg'] is not None:
        df['pressure'] = [daily_avg['pressure_avg']]
    
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
        
        # Reset daily weather readings for the new day
        state.weather.reset_daily_readings()
        _LOGGER.debug("Reset daily weather readings for new day")
    
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
