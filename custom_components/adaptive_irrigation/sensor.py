"""Sensor entities for Adaptive Irrigation."""

from __future__ import annotations

import logging

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTime
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, get_device_info

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Adaptive Irrigation sensor platform."""
    _LOGGER.debug("Setting up Adaptive Irrigation sensor platform")

    device_info = get_device_info(entry)
    
    # Get zones from config
    config_data = {**entry.data, **entry.options}
    zones = config_data.get("zones", [])
    
    sensors = []
    
    # Create runtime sensor for each zone
    for idx, zone in enumerate(zones):
        zone_id = f"zone_{idx}"
        precipitation_rate = zone.get("precipitation_rate", 10.0)
        sensor = RequiredRuntimeSensor(
            entry, 
            device_info, 
            zone_id, 
            zone.get("name", f"Zone {idx + 1}"),
            precipitation_rate
        )
        sensors.append(sensor)
    
    # Store entity references in the entry-specific data
    if "entities" not in hass.data[DOMAIN][entry.entry_id]:
        hass.data[DOMAIN][entry.entry_id]["entities"] = {}
    
    for sensor in sensors:
        zone_id = sensor._zone_id
        hass.data[DOMAIN][entry.entry_id]["entities"][f"runtime_{zone_id}"] = sensor
    
    async_add_entities(sensors)


class RequiredRuntimeSensor(SensorEntity):
    """Sensor showing required sprinkler runtime to reach optimal moisture (0mm balance).
    
    Returns time in seconds needed to eliminate moisture deficit.
    Returns 0 if balance is 0 or positive (no deficit).
    """

    _attr_has_entity_name = True
    _attr_device_class = SensorDeviceClass.DURATION
    _attr_native_unit_of_measurement = UnitOfTime.SECONDS
    _attr_should_poll = False

    def __init__(
        self, 
        entry: ConfigEntry, 
        device_info, 
        zone_id: str, 
        zone_name: str,
        precipitation_rate: float
    ) -> None:
        """Initialize the sensor."""
        self._zone_id = zone_id
        self._precipitation_rate = precipitation_rate  # mm/hour
        self._attr_name = f"{zone_name} Required Runtime"
        self._attr_unique_id = f"{entry.entry_id}_{zone_id}_required_runtime"
        self._attr_native_value = 0
        self._attr_device_info = device_info

    @callback
    def update_from_balance(self, balance: float) -> None:
        """Update runtime calculation based on current balance."""
        if balance >= 0:
            # No deficit or excess moisture - no watering needed
            runtime_seconds = 0
        else:
            # Calculate time needed to eliminate deficit
            # balance is negative, so abs(balance) gives deficit in mm
            deficit_mm = abs(balance)
            
            # Time (hours) = deficit (mm) / precipitation_rate (mm/hour)
            # Time (seconds) = hours * 3600
            runtime_seconds = (deficit_mm / self._precipitation_rate) * 3600
        
        self._attr_native_value = round(runtime_seconds)
        self.async_write_ha_state()
        
    @callback
    def update_precipitation_rate(self, rate: float) -> None:
        """Update precipitation rate if config changes."""
        self._precipitation_rate = rate
