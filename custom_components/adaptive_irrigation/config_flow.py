"""Config flow for Adaptive Irrigation integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

DEFAULT_CROP_COEFFICIENT = 1.0


def _filter_none_values(data: dict[str, Any]) -> dict[str, Any]:
    """Remove None values from dictionary to prevent entity validation errors."""
    return {k: v for k, v in data.items() if v is not None}


class AdaptiveIrrigationConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Adaptive Irrigation."""

    VERSION = 1
    MINOR_VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: ConfigEntry,
    ) -> AdaptiveIrrigationOptionsFlow:
        """Get the options flow for this handler."""
        return AdaptiveIrrigationOptionsFlow(config_entry)

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._basic_config: dict[str, Any] = {}
        self._num_zones: int = 0
        self._current_zone_index: int = 0
        self._zones: list[dict[str, Any]] = []
        self._name: str = ""

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step - name and weather sensors."""
        errors = {}

        if user_input is not None:
            try:
                # Store name and create unique ID
                self._name = user_input["name"]

                await self.async_set_unique_id(self._name.lower().replace(" ", "_"))
                self._abort_if_unique_id_configured()

                # Store the weather sensor configuration
                self._basic_config.update(_filter_none_values(user_input))
                return await self.async_step_location()
            except Exception as e:
                errors["base"] = "unknown"
                _LOGGER.exception("Error in user step: %s", e)

        schema = vol.Schema(
            {
                vol.Required(
                    "name", default="Adaptive Irrigation"
                ): selector.TextSelector(),
                vol.Required("temperature_entity"): selector.EntitySelector(
                    selector.EntitySelectorConfig(
                        domain=["sensor", "input_number"], multiple=False
                    )
                ),
                vol.Required("humidity_entity"): selector.EntitySelector(
                    selector.EntitySelectorConfig(
                        domain=["sensor", "input_number"], multiple=False
                    )
                ),
                vol.Required("precipitation_entity"): selector.EntitySelector(
                    selector.EntitySelectorConfig(
                        domain=["sensor", "input_number"], multiple=False
                    )
                ),
                vol.Optional("wind_speed_entity"): selector.EntitySelector(
                    selector.EntitySelectorConfig(
                        domain=["sensor", "input_number"], multiple=False
                    )
                ),
                vol.Optional("solar_radiation_entity"): selector.EntitySelector(
                    selector.EntitySelectorConfig(
                        domain=["sensor", "input_number"], multiple=False
                    )
                ),
                vol.Optional("pressure_entity"): selector.EntitySelector(
                    selector.EntitySelectorConfig(
                        domain=["sensor", "input_number"], multiple=False
                    )
                ),
                vol.Optional("forecast_rain_entity"): selector.EntitySelector(
                    selector.EntitySelectorConfig(
                        domain=["sensor", "input_number", "number"], multiple=False
                    )
                ),
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    async def async_step_location(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle location and ET method configuration."""
        if user_input is not None:
            self._basic_config.update(_filter_none_values(user_input))
            return await self.async_step_zones()

        # Get default location from Home Assistant config
        latitude = self.hass.config.latitude
        longitude = self.hass.config.longitude
        elevation = self.hass.config.elevation

        schema = vol.Schema(
            {
                vol.Required("latitude", default=latitude): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=-90, max=90, mode=selector.NumberSelectorMode.BOX
                    )
                ),
                vol.Required("longitude", default=longitude): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=-180, max=180, mode=selector.NumberSelectorMode.BOX
                    )
                ),
                vol.Required("elevation", default=elevation): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0, mode=selector.NumberSelectorMode.BOX
                    )
                ),
            }
        )
        return self.async_show_form(step_id="location", data_schema=schema)

    async def async_step_zones(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the irrigation zones step."""
        if user_input is not None:
            # Get the number of zones to configure
            num_zones = user_input.get("num_zones", 0)
            if num_zones > 0:
                self._num_zones = num_zones
                self._zones = []
                self._current_zone_index = 0
                return await self.async_step_zone_config()
            # No zones configured, finish setup
            self._basic_config["zones"] = []
            return self.async_create_entry(title=self._name, data=self._basic_config)

        schema = vol.Schema(
            {
                vol.Required("num_zones", default=1): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0, max=20, mode=selector.NumberSelectorMode.BOX
                    )
                ),
            }
        )
        return self.async_show_form(step_id="zones", data_schema=schema)

    async def async_step_zone_config(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Configure individual zone."""
        if user_input is not None:
            # Store this zone configuration
            self._zones.append(_filter_none_values(user_input))
            self._current_zone_index += 1

            # Check if we need to configure more zones
            if self._current_zone_index < self._num_zones:
                return await self.async_step_zone_config()

            # All zones configured, finish setup
            self._basic_config["zones"] = self._zones
            return self.async_create_entry(title=self._name, data=self._basic_config)

        schema = vol.Schema(
            {
                vol.Required("name"): selector.TextSelector(),
                vol.Required("sprinkler_entity"): selector.EntitySelector(
                    selector.EntitySelectorConfig(
                        domain=["switch", "input_boolean", "valve", "binary_sensor"]
                    )
                ),
                vol.Required(
                    "precipitation_rate", default=10.0
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0,
                        mode=selector.NumberSelectorMode.BOX,
                        unit_of_measurement="mm/hour",
                    )
                ),
                vol.Optional("drainage_rate", default=1.0): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0,
                        max=50,
                        mode=selector.NumberSelectorMode.BOX,
                        unit_of_measurement="mm/day",
                    )
                ),
                vol.Optional(
                    "crop_coefficient", default=DEFAULT_CROP_COEFFICIENT
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0, max=2, mode=selector.NumberSelectorMode.BOX
                    )
                ),
                vol.Optional("max_runtime", default=3600): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0,
                        mode=selector.NumberSelectorMode.BOX,
                        unit_of_measurement="seconds",
                    )
                ),
                vol.Optional("min_runtime", default=60): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0,
                        mode=selector.NumberSelectorMode.BOX,
                        unit_of_measurement="seconds",
                    )
                ),
                vol.Optional("minimum_interval", default=3600): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0,
                        mode=selector.NumberSelectorMode.BOX,
                        unit_of_measurement="seconds",
                    )
                ),
                vol.Optional("max_balance", default=5.0): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=-200,
                        max=200,
                        mode=selector.NumberSelectorMode.BOX,
                        unit_of_measurement="mm",
                    )
                ),
                vol.Optional("min_balance", default=-20.0): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=-200,
                        max=200,
                        mode=selector.NumberSelectorMode.BOX,
                        unit_of_measurement="mm",
                    )
                ),
            }
        )
        return self.async_show_form(
            step_id="zone_config",
            data_schema=schema,
            description_placeholders={
                "zone_number": str(self._current_zone_index + 1),
                "total_zones": str(self._num_zones),
            },
        )


class AdaptiveIrrigationOptionsFlow(OptionsFlow):
    """Handle options flow for Adaptive Irrigation."""

    def __init__(self, config_entry: ConfigEntry) -> None:
        """Initialize options flow."""
        super().__init__()
        self._edit_zone_index: int | None = None

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage the options."""
        return await self.async_step_menu()

    async def async_step_menu(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show main options menu."""
        return self.async_show_menu(
            step_id="menu",
            menu_options=["weather_sensors", "location", "manage_zones"],
        )

    async def async_step_weather_sensors(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Configure weather sensors."""
        if user_input is not None:
            current_options = {**self.config_entry.data, **self.config_entry.options}
            updated_options = {**current_options, **_filter_none_values(user_input)}
            return self.async_create_entry(title="", data=updated_options)

        current_config = {**self.config_entry.data, **self.config_entry.options}

        schema_fields = {
            vol.Required(
                "temperature_entity",
                default=current_config.get("temperature_entity"),
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(domain=["sensor", "input_number"])
            ),
            vol.Required(
                "humidity_entity",
                default=current_config.get("humidity_entity"),
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(domain=["sensor", "input_number"])
            ),
            vol.Required(
                "precipitation_entity",
                default=current_config.get("precipitation_entity"),
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(domain=["sensor", "input_number"])
            ),
        }

        # Add optional entities with defaults if they exist
        wind_entity = current_config.get("wind_speed_entity")
        if wind_entity:
            schema_fields[vol.Optional("wind_speed_entity", default=wind_entity)] = (
                selector.EntitySelector(
                    selector.EntitySelectorConfig(domain=["sensor", "input_number"])
                )
            )
        else:
            schema_fields[vol.Optional("wind_speed_entity")] = selector.EntitySelector(
                selector.EntitySelectorConfig(domain=["sensor", "input_number"])
            )

        solar_entity = current_config.get("solar_radiation_entity")
        if solar_entity:
            schema_fields[
                vol.Optional("solar_radiation_entity", default=solar_entity)
            ] = selector.EntitySelector(
                selector.EntitySelectorConfig(domain=["sensor", "input_number"])
            )
        else:
            schema_fields[vol.Optional("solar_radiation_entity")] = (
                selector.EntitySelector(
                    selector.EntitySelectorConfig(domain=["sensor", "input_number"])
                )
            )

        pressure_entity = current_config.get("pressure_entity")
        if pressure_entity:
            schema_fields[vol.Optional("pressure_entity", default=pressure_entity)] = (
                selector.EntitySelector(
                    selector.EntitySelectorConfig(domain=["sensor", "input_number"])
                )
            )
        else:
            schema_fields[vol.Optional("pressure_entity")] = selector.EntitySelector(
                selector.EntitySelectorConfig(domain=["sensor", "input_number"])
            )

        forecast_rain_entity = current_config.get("forecast_rain_entity")
        if forecast_rain_entity:
            schema_fields[vol.Optional("forecast_rain_entity", default=forecast_rain_entity)] = (
                selector.EntitySelector(
                    selector.EntitySelectorConfig(domain=["sensor", "input_number", "number"])
                )
            )
        else:
            schema_fields[vol.Optional("forecast_rain_entity")] = selector.EntitySelector(
                selector.EntitySelectorConfig(domain=["sensor", "input_number", "number"])
            )

        schema = vol.Schema(schema_fields)
        return self.async_show_form(step_id="weather_sensors", data_schema=schema)

    async def async_step_location(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Configure location and ET settings."""
        if user_input is not None:
            current_options = {**self.config_entry.data, **self.config_entry.options}
            updated_options = {**current_options, **_filter_none_values(user_input)}
            return self.async_create_entry(title="", data=updated_options)

        current_config = {**self.config_entry.data, **self.config_entry.options}

        schema = vol.Schema(
            {
                vol.Required(
                    "latitude",
                    default=current_config.get("latitude", self.hass.config.latitude),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=-90, max=90, mode=selector.NumberSelectorMode.BOX
                    )
                ),
                vol.Required(
                    "longitude",
                    default=current_config.get("longitude", self.hass.config.longitude),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=-180, max=180, mode=selector.NumberSelectorMode.BOX
                    )
                ),
                vol.Required(
                    "elevation",
                    default=current_config.get("elevation", self.hass.config.elevation),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0, mode=selector.NumberSelectorMode.BOX
                    )
                ),
            }
        )
        return self.async_show_form(step_id="location", data_schema=schema)

    async def async_step_manage_zones(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage irrigation zones."""
        current_config = {**self.config_entry.data, **self.config_entry.options}
        current_zones = current_config.get("zones", [])

        menu_options = ["add_zone"]
        if current_zones:
            menu_options.append("select_zone_to_edit")
        menu_options.append("menu")

        return self.async_show_menu(
            step_id="manage_zones",
            menu_options=menu_options,
        )

    async def async_step_add_zone(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Add a new zone."""
        if user_input is not None:
            current_config = {**self.config_entry.data, **self.config_entry.options}
            zones = list(current_config.get("zones", []))
            zones.append(_filter_none_values(user_input))
            updated_options = {**current_config, "zones": zones}
            return self.async_create_entry(title="", data=updated_options)

        schema = vol.Schema(
            {
                vol.Required("name"): selector.TextSelector(),
                vol.Required("sprinkler_entity"): selector.EntitySelector(
                    selector.EntitySelectorConfig(
                        domain=["switch", "input_boolean", "valve", "binary_sensor"]
                    )
                ),
                vol.Required(
                    "precipitation_rate", default=10.0
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0,
                        mode=selector.NumberSelectorMode.BOX,
                        unit_of_measurement="mm/hour",
                    )
                ),
                vol.Optional("drainage_rate", default=1.0): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0,
                        max=50,
                        mode=selector.NumberSelectorMode.BOX,
                        unit_of_measurement="mm/day",
                    )
                ),
                vol.Optional(
                    "crop_coefficient", default=DEFAULT_CROP_COEFFICIENT
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0, max=2, mode=selector.NumberSelectorMode.BOX
                    )
                ),
                vol.Optional("max_runtime", default=3600): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0,
                        mode=selector.NumberSelectorMode.BOX,
                        unit_of_measurement="seconds",
                    )
                ),
                vol.Optional("min_runtime", default=60): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0,
                        mode=selector.NumberSelectorMode.BOX,
                        unit_of_measurement="seconds",
                    )
                ),
                vol.Optional("minimum_interval", default=3600): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0,
                        mode=selector.NumberSelectorMode.BOX,
                        unit_of_measurement="seconds",
                    )
                ),
                vol.Optional("max_balance", default=5.0): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=-200,
                        max=200,
                        mode=selector.NumberSelectorMode.BOX,
                        unit_of_measurement="mm",
                    )
                ),
                vol.Optional("min_balance", default=-20.0): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=-200,
                        max=200,
                        mode=selector.NumberSelectorMode.BOX,
                        unit_of_measurement="mm",
                    )
                ),
            }
        )
        return self.async_show_form(step_id="add_zone", data_schema=schema)

    async def async_step_select_zone_to_edit(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Select which zone to edit."""
        current_config = {**self.config_entry.data, **self.config_entry.options}
        zones = current_config.get("zones", [])

        if user_input is not None:
            selected_zone = user_input.get("zone_to_edit")
            self._edit_zone_index = int(selected_zone)
            return await self.async_step_edit_zone()

        # Create list of zone names for selection
        zone_options = {
            str(i): zone.get("name", f"Zone {i + 1}") for i, zone in enumerate(zones)
        }

        schema = vol.Schema(
            {
                vol.Required("zone_to_edit"): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[
                            {"label": name, "value": idx}
                            for idx, name in zone_options.items()
                        ],
                        mode=selector.SelectSelectorMode.LIST,
                    )
                ),
            }
        )
        return self.async_show_form(step_id="select_zone_to_edit", data_schema=schema)

    async def async_step_edit_zone(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Edit or delete a zone."""
        current_config = {**self.config_entry.data, **self.config_entry.options}
        zones = list(current_config.get("zones", []))
        current_zone = zones[self._edit_zone_index]

        if user_input is not None:
            if user_input.get("delete_zone"):
                # Delete the zone
                zones.pop(self._edit_zone_index)
                updated_options = {**current_config, "zones": zones}
                return self.async_create_entry(title="", data=updated_options)

            # Update the zone
            user_input.pop("delete_zone", None)
            zones[self._edit_zone_index] = _filter_none_values(user_input)
            updated_options = {**current_config, "zones": zones}
            return self.async_create_entry(title="", data=updated_options)

        schema = vol.Schema(
            {
                vol.Required(
                    "name", default=current_zone.get("name", "")
                ): selector.TextSelector(),
                vol.Required(
                    "sprinkler_entity",
                    default=current_zone.get("sprinkler_entity"),
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(
                        domain=["switch", "input_boolean", "valve", "binary_sensor"]
                    )
                ),
                vol.Required(
                    "precipitation_rate",
                    default=current_zone.get("precipitation_rate", 10.0),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0,
                        mode=selector.NumberSelectorMode.BOX,
                        unit_of_measurement="mm/hour",
                    )
                ),
                vol.Optional(
                    "drainage_rate",
                    default=current_zone.get("drainage_rate", 1.0),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0,
                        max=50,
                        mode=selector.NumberSelectorMode.BOX,
                        unit_of_measurement="mm/day",
                    )
                ),
                vol.Optional(
                    "crop_coefficient",
                    default=current_zone.get(
                        "crop_coefficient", DEFAULT_CROP_COEFFICIENT
                    ),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0, max=2, mode=selector.NumberSelectorMode.BOX
                    )
                ),
                vol.Optional(
                    "max_runtime",
                    default=current_zone.get("max_runtime", 3600),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0,
                        mode=selector.NumberSelectorMode.BOX,
                        unit_of_measurement="seconds",
                    )
                ),
                vol.Optional(
                    "min_runtime",
                    default=current_zone.get("min_runtime", 60),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0,
                        mode=selector.NumberSelectorMode.BOX,
                        unit_of_measurement="seconds",
                    )
                ),
                vol.Optional(
                    "minimum_interval",
                    default=current_zone.get("minimum_interval", 3600),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0,
                        mode=selector.NumberSelectorMode.BOX,
                        unit_of_measurement="seconds",
                    )
                ),
                vol.Optional(
                    "max_balance",
                    default=current_zone.get("max_balance", 5.0),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=-200,
                        max=200,
                        mode=selector.NumberSelectorMode.BOX,
                        unit_of_measurement="mm",
                    )
                ),
                vol.Optional(
                    "min_balance",
                    default=current_zone.get("min_balance", -20.0),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=-200,
                        max=200,
                        mode=selector.NumberSelectorMode.BOX,
                        unit_of_measurement="mm",
                    )
                ),
                vol.Required("delete_zone", default=False): selector.BooleanSelector(),
            }
        )
        return self.async_show_form(
            step_id="edit_zone",
            data_schema=schema,
            description_placeholders={"zone_name": current_zone.get("name", "Zone")},
        )
