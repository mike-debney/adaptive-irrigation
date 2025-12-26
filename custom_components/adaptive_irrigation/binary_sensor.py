"""Binary sensor entities for Adaptive Irrigation."""

from __future__ import annotations

from datetime import datetime, timedelta
import logging

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_time_interval

from .const import DOMAIN, get_device_info

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Adaptive Irrigation binary sensor platform."""
    _LOGGER.debug("Setting up Adaptive Irrigation binary sensor platform")

    device_info = get_device_info(entry)
    
    # Get zones from config
    config_data = {**entry.data, **entry.options}
    zones = config_data.get("zones", [])
    
    binary_sensors = []
    
    # Create can run binary sensor for each zone
    for idx, zone in enumerate(zones):
        zone_id = f"zone_{idx}"
        binary_sensor = ZoneCanRunBinarySensor(entry, device_info, zone_id, zone.get("name", f"Zone {idx + 1}"))
        binary_sensors.append(binary_sensor)
    
    # Store entity references in the entry-specific data
    if "entities" not in hass.data[DOMAIN][entry.entry_id]:
        hass.data[DOMAIN][entry.entry_id]["entities"] = {}
    
    for binary_sensor in binary_sensors:
        zone_id = binary_sensor._zone_id
        hass.data[DOMAIN][entry.entry_id]["entities"][f"can_run_{zone_id}"] = binary_sensor
    
    async_add_entities(binary_sensors)


class ZoneCanRunBinarySensor(BinarySensorEntity):
    """Binary sensor indicating if a zone can run based on scheduling constraints."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, entry: ConfigEntry, device_info, zone_id: str, zone_name: str) -> None:
        """Initialize the binary sensor entity."""
        self._zone_id = zone_id
        self._entry_id = entry.entry_id
        self._attr_name = f"{zone_name} Can Run"
        self._attr_unique_id = f"{entry.entry_id}_{zone_id}_can_run"
        self._attr_is_on = False
        self._attr_device_info = device_info
    
    async def async_added_to_hass(self) -> None:
        """Run when entity is added to hass - set up periodic updates."""
        await super().async_added_to_hass()
        
        # Update every minute to re-check minimum interval condition
        self.async_on_remove(
            async_track_time_interval(
                self.hass,
                self._periodic_update,
                timedelta(minutes=1)
            )
        )
    
    @callback
    def _periodic_update(self, now: datetime) -> None:
        """Periodic update to re-check can run conditions."""
        self.update_can_run()

    @callback
    def update_can_run(self) -> None:
        """Update whether the zone can run and notify HA."""
        if DOMAIN not in self.hass.data or self._entry_id not in self.hass.data[DOMAIN]:
            self._attr_is_on = False
            self.async_write_ha_state()
            return
        
        entry_data = self.hass.data[DOMAIN][self._entry_id]
        config = entry_data.get("config")
        state = entry_data.get("state")
        
        if not config or not state or self._zone_id not in config.zones:
            self._attr_is_on = False
            self.async_write_ha_state()
            return
        
        zone_config = config.zones[self._zone_id]
        zone_state = state.zones[self._zone_id]
        
        # Check all conditions
        can_run = True
        balance = zone_state.soil_moisture_balance
        
        # 1. Check minimum interval has passed
        if zone_state.sprinkler_off_time is not None:
            time_since_off = (datetime.now() - zone_state.sprinkler_off_time).total_seconds()
            if time_since_off < zone_config.minimum_interval:
                _LOGGER.debug("Zone %s cannot run: only %.0f seconds since last off (need %.0f)", 
                             zone_config.name, time_since_off, zone_config.minimum_interval)
                can_run = False
        
        # 2. Check that calculated runtime meets minimum
        if balance < 0:  # Only if there's a deficit
            # Calculate required runtime
            deficit_mm = abs(balance)
            runtime_hours = deficit_mm / zone_config.precipitation_rate
            runtime_seconds = runtime_hours * 3600
            
            if runtime_seconds < zone_config.min_runtime:
                _LOGGER.debug("Zone %s cannot run: calculated runtime %.0f < min %.0f seconds", 
                             zone_config.name, runtime_seconds, zone_config.min_runtime)
                can_run = False
        else:
            # No deficit, no need to run
            can_run = False
        
        self._attr_is_on = can_run
        self.async_write_ha_state()
