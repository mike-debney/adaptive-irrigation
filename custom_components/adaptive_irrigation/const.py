"""Constants for the Adaptive Irrigation integration."""

from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.device_registry import DeviceInfo

DOMAIN = "adaptive_irrigation"

# ET calculation methods
ET_METHOD_PENMAN_MONTEITH = "penman_monteith"
ET_METHOD_HARGREAVES = "hargreaves"
ET_METHOD_PRIESTLEY_TAYLOR = "priestley_taylor"

ET_METHODS = [
    ET_METHOD_PENMAN_MONTEITH,
    ET_METHOD_HARGREAVES,
    ET_METHOD_PRIESTLEY_TAYLOR,
]


def get_device_info(entry: ConfigEntry) -> DeviceInfo:
    """Get device info for the Adaptive Irrigation controller."""
    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name="Adaptive Irrigation Controller",
        manufacturer="Adaptive Irrigation",
        model="Irrigation Controller",
        entry_type=None,
    )
