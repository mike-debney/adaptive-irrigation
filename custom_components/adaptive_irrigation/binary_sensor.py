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
    """Binary sensor indicating if a zone can run based on scheduling constraints.
    
    This entity simply reads pre-calculated values from state.
    All calculation logic is handled by the coordinator.
    """

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, entry: ConfigEntry, device_info, zone_id: str, zone_name: str) -> None:
        """Initialize the binary sensor entity."""
        self._zone_id = zone_id
        self._zone_name = zone_name
        self._entry_id = entry.entry_id
        self._attr_name = f"{zone_name} Can Run"
        self._attr_unique_id = f"{entry.entry_id}_{zone_id}_can_run"
        self._attr_is_on = False
        self._attr_device_info = device_info
    
    async def async_added_to_hass(self) -> None:
        """Run when entity is added to hass - set up periodic updates."""
        await super().async_added_to_hass()
        
        # Periodic refresh to re-check minimum interval condition
        # (coordinator recalculates, then we refresh from state)
        self.async_on_remove(
            async_track_time_interval(
                self.hass,
                self._periodic_refresh,
                timedelta(minutes=1)
            )
        )
    
    @callback
    def _periodic_refresh(self, now: datetime) -> None:
        """Periodic refresh - trigger recalculation via coordinator."""
        # Import here to avoid circular imports
        from . import update_runtime_sensors
        update_runtime_sensors(self.hass, self._entry_id, self._zone_id)

    @callback
    def refresh_from_state(self) -> None:
        """Refresh entity value from pre-calculated state."""
        if DOMAIN not in self.hass.data or self._entry_id not in self.hass.data[DOMAIN]:
            self._attr_is_on = False
            self.async_write_ha_state()
            return
        
        entry_data = self.hass.data[DOMAIN][self._entry_id]
        state = entry_data.get("state")
        config = entry_data.get("config")
        
        if not state or self._zone_id not in state.zones:
            self._attr_is_on = False
            self.async_write_ha_state()
            return
        
        zone_state = state.zones[self._zone_id]
        zone_config = config.zones.get(self._zone_id) if config else None
        
        # Read pre-calculated value from state
        self._attr_is_on = zone_state.calculated.can_run
        
        if not zone_state.calculated.can_run and zone_config:
            _LOGGER.debug("Zone %s cannot run: %s", zone_config.name, zone_state.calculated.reason)
        
        self.async_write_ha_state()

