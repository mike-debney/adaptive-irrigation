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
    
    # Create reference ET sensor (single, integration-level)
    et0_sensor = ReferenceETSensor(entry, device_info)
    sensors.append(et0_sensor)
    
    # Create runtime sensors for each zone
    for idx, zone in enumerate(zones):
        zone_id = f"zone_{idx}"
        precipitation_rate = zone.get("precipitation_rate", 10.0)
        
        # Required runtime sensor (basic calculation)
        required_sensor = RequiredRuntimeSensor(
            entry, 
            device_info, 
            zone_id, 
            zone.get("name", f"Zone {idx + 1}"),
            precipitation_rate
        )
        sensors.append(required_sensor)
        
        # Next runtime sensor (with scheduling constraints)
        next_sensor = NextRuntimeSensor(
            entry,
            device_info,
            zone_id,
            zone.get("name", f"Zone {idx + 1}")
        )
        sensors.append(next_sensor)
    
    # Store entity references in the entry-specific data
    if "entities" not in hass.data[DOMAIN][entry.entry_id]:
        hass.data[DOMAIN][entry.entry_id]["entities"] = {}
    
    # Store ET0 sensor reference
    hass.data[DOMAIN][entry.entry_id]["entities"]["et0_sensor"] = et0_sensor
    
    for sensor in sensors:
        if isinstance(sensor, ReferenceETSensor):
            continue  # Already stored above
        zone_id = sensor._zone_id
        if isinstance(sensor, RequiredRuntimeSensor):
            hass.data[DOMAIN][entry.entry_id]["entities"][f"runtime_{zone_id}"] = sensor
        elif isinstance(sensor, NextRuntimeSensor):
            hass.data[DOMAIN][entry.entry_id]["entities"][f"next_runtime_{zone_id}"] = sensor
    
    async_add_entities(sensors)


class ReferenceETSensor(SensorEntity):
    """Sensor showing reference evapotranspiration (ET0) from yesterday.
    
    This is the ET value before crop coefficient adjustment.
    """

    _attr_has_entity_name = True
    _attr_native_unit_of_measurement = "mm"
    _attr_should_poll = False
    _attr_suggested_display_precision = 2

    def __init__(self, entry: ConfigEntry, device_info) -> None:
        """Initialize the sensor."""
        self._entry_id = entry.entry_id
        self._attr_name = "Yesterday Reference Evapotranspiration"
        self._attr_unique_id = f"{entry.entry_id}_yesterday_reference_et"
        self._attr_native_value = None
        self._attr_device_info = device_info

    @callback
    def update_et0(self, et0_value: float) -> None:
        """Update the ET0 value and notify HA."""
        self._attr_native_value = round(et0_value, 2)
        self.async_write_ha_state()


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


class NextRuntimeSensor(SensorEntity):
    """Sensor showing next runtime accounting for scheduling constraints.
    
    Returns time in seconds for the next irrigation run, accounting for:
    - Minimum runtime
    - Maximum runtime
    - Balance limits
    Returns 0 if zone cannot run.
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
        zone_name: str
    ) -> None:
        """Initialize the sensor."""
        self._zone_id = zone_id
        self._entry_id = entry.entry_id
        self._attr_name = f"{zone_name} Next Runtime"
        self._attr_unique_id = f"{entry.entry_id}_{zone_id}_next_runtime"
        self._attr_native_value = 0
        self._attr_device_info = device_info

    @callback
    def update_next_runtime(self) -> None:
        """Update next runtime calculation accounting for constraints."""
        if DOMAIN not in self.hass.data or self._entry_id not in self.hass.data[DOMAIN]:
            self._attr_native_value = 0
            self.async_write_ha_state()
            return
        
        entry_data = self.hass.data[DOMAIN][self._entry_id]
        config = entry_data.get("config")
        state = entry_data.get("state")
        
        if not config or not state or self._zone_id not in config.zones:
            self._attr_native_value = 0
            self.async_write_ha_state()
            return
        
        zone_config = config.zones[self._zone_id]
        zone_state = state.zones[self._zone_id]
        balance = zone_state.soil_moisture_balance
        
        # Check if zone can run (same logic as binary sensor)
        # Get can_run sensor to check
        can_run_entities = entry_data.get("entities", {})
        can_run_key = f"can_run_{self._zone_id}"
        
        if can_run_key in can_run_entities:
            can_run = can_run_entities[can_run_key].is_on
        else:
            # Fallback: check manually (balance < 0 means deficit exists)
            can_run = balance < 0
        
        if not can_run or balance >= 0:
            self._attr_native_value = 0
            self.async_write_ha_state()
            return
        
        # Calculate base runtime
        deficit_mm = abs(balance)
        runtime_hours = deficit_mm / zone_config.precipitation_rate
        runtime_seconds = runtime_hours * 3600
        
        # Clamp to min/max limits
        runtime_seconds = max(zone_config.min_runtime, min(runtime_seconds, zone_config.max_runtime))
        
        self._attr_native_value = round(runtime_seconds)
        self.async_write_ha_state()
