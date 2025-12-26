"""Number entities for Adaptive Irrigation."""

from __future__ import annotations

import logging

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.restore_state import RestoreEntity

from .const import DOMAIN, get_device_info

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Adaptive Irrigation number platform."""
    _LOGGER.debug("Setting up Adaptive Irrigation number platform")

    device_info = get_device_info(entry)
    
    # Get zones from config
    config_data = {**entry.data, **entry.options}
    zones = config_data.get("zones", [])
    
    numbers = []
    
    # Create soil moisture balance number for each zone
    for idx, zone in enumerate(zones):
        zone_id = f"zone_{idx}"
        number = SoilMoistureBalanceNumber(entry, device_info, zone_id, zone.get("name", f"Zone {idx + 1}"))
        numbers.append(number)
    
    # Store entity references in the entry-specific data
    if "entities" not in hass.data[DOMAIN][entry.entry_id]:
        hass.data[DOMAIN][entry.entry_id]["entities"] = {}
    
    for number in numbers:
        zone_id = number._zone_id
        hass.data[DOMAIN][entry.entry_id]["entities"][f"soil_moisture_balance_{zone_id}"] = number
    
    async_add_entities(numbers)


class SoilMoistureBalanceNumber(RestoreEntity, NumberEntity):
    """Number entity for soil moisture balance in a zone.
    
    Balance is measured in mm where:
    - 0mm = optimal moisture level
    - Positive values = excess moisture (too wet)
    - Negative values = moisture deficit (too dry)
    """

    _attr_has_entity_name = True
    _attr_native_unit_of_measurement = "mm"
    _attr_mode = NumberMode.BOX
    _attr_native_min_value = -200.0
    _attr_native_max_value = 200.0
    _attr_native_step = 0.1
    _attr_should_poll = False

    def __init__(self, entry: ConfigEntry, device_info, zone_id: str, zone_name: str) -> None:
        """Initialize the number entity."""
        self._zone_id = zone_id
        self._entry_id = entry.entry_id
        self._attr_name = f"{zone_name} Soil Moisture Balance"
        self._attr_unique_id = f"{entry.entry_id}_{zone_id}_soil_moisture_balance"
        self._attr_native_value = 0.0  # Default to optimal (0mm balance)
        self._attr_device_info = device_info
    
    async def async_added_to_hass(self) -> None:
        """Run when entity is added to hass - restore state if available."""
        await super().async_added_to_hass()
        
        # Try to restore previous state
        last_state = await self.async_get_last_state()
        
        if last_state is not None and last_state.state not in ("unknown", "unavailable"):
            try:
                self._attr_native_value = float(last_state.state)
                _LOGGER.info("Restored soil moisture balance for zone %s: %.2f mm", self._zone_id, self._attr_native_value)
            except (ValueError, TypeError):
                _LOGGER.warning("Could not restore balance for zone %s, starting at 0mm", self._zone_id)
                self._attr_native_value = 0.0
        else:
            _LOGGER.info("No previous state for zone %s, starting at 0mm", self._zone_id)
            self._attr_native_value = 0.0
        
        # Update the integration's state to match restored value
        if DOMAIN in self.hass.data and self._entry_id in self.hass.data[DOMAIN]:
            state = self.hass.data[DOMAIN][self._entry_id].get("state")
            if state and self._zone_id in state.zones:
                state.zones[self._zone_id].soil_moisture_balance = self._attr_native_value
                _LOGGER.debug("Synced integration state with restored balance: %.2f mm", self._attr_native_value)
        
        # Schedule update of sensors after a short delay to ensure all entities are loaded
        @callback
        def delayed_update(_now):
            """Update sensors after delay."""
            self._update_runtime_sensor(self._attr_native_value)
        
        async_call_later(self.hass, 1, delayed_update)

    @callback
    def update_value(self, balance: float) -> None:
        """Update the balance value and notify HA."""
        self._attr_native_value = round(balance, 2)
        self.async_write_ha_state()
        
        # Also update the runtime sensor
        self._update_runtime_sensor(balance)
    
    async def async_set_native_value(self, value: float) -> None:
        """Update the current value (user override)."""
        self._attr_native_value = value
        self.async_write_ha_state()
        
        # Update the state in our integration's state management
        if DOMAIN in self.hass.data and self._entry_id in self.hass.data[DOMAIN]:
            state = self.hass.data[DOMAIN][self._entry_id].get("state")
            if state and self._zone_id in state.zones:
                state.zones[self._zone_id].soil_moisture_balance = value
                _LOGGER.info(
                    "User manually set soil moisture balance for zone %s to %.2f mm",
                    self._zone_id,
                    value
                )
        
        # Also update the runtime sensor
        self._update_runtime_sensor(value)
    
    def _update_runtime_sensor(self, balance: float) -> None:
        """Update the corresponding runtime sensors and binary sensor."""
        if DOMAIN in self.hass.data and self._entry_id in self.hass.data[DOMAIN]:
            entities = self.hass.data[DOMAIN][self._entry_id].get("entities", {})
            
            # Update required runtime sensor
            runtime_key = f"runtime_{self._zone_id}"
            if runtime_key in entities:
                runtime_sensor = entities[runtime_key]
                runtime_sensor.update_from_balance(balance)
            
            # Update can run binary sensor
            can_run_key = f"can_run_{self._zone_id}"
            if can_run_key in entities:
                can_run_sensor = entities[can_run_key]
                can_run_sensor.update_can_run()
            
            # Update next runtime sensor
            next_runtime_key = f"next_runtime_{self._zone_id}"
            if next_runtime_key in entities:
                next_runtime_sensor = entities[next_runtime_key]
                next_runtime_sensor.update_next_runtime()
