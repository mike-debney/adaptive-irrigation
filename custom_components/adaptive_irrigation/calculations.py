"""Centralized irrigation calculations for Adaptive Irrigation integration.

This module contains all the core calculation logic. The coordinator calls
these functions to update pre-calculated values in state, and entities
simply read from state for display.
"""

from __future__ import annotations

from datetime import datetime
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from .config import Config, ZoneConfig
    from .state import ZoneState

_LOGGER = logging.getLogger(__name__)


def get_forecast_rain(hass: HomeAssistant, config: Config) -> float:
    """Get forecasted rain amount from configured entity.
    
    Args:
        hass: Home Assistant instance
        config: Integration configuration
        
    Returns:
        Forecasted rain in mm, or 0.0 if unavailable
    """
    if not config or not config.weather_sensors.forecast_rain_entity:
        return 0.0
    
    forecast_state = hass.states.get(config.weather_sensors.forecast_rain_entity)
    if forecast_state and forecast_state.state not in ("unknown", "unavailable"):
        try:
            return max(0.0, float(forecast_state.state))
        except (ValueError, TypeError):
            _LOGGER.warning("Invalid forecast rain value: %s", forecast_state.state)
    
    return 0.0


def calculate_effective_deficit(
    balance: float,
    forecast_rain: float
) -> float:
    """Calculate effective moisture deficit accounting for forecasted rain.
    
    Args:
        balance: Current soil moisture balance (negative = deficit)
        forecast_rain: Forecasted rain in mm
        
    Returns:
        Effective deficit in mm (always >= 0), or 0 if no deficit
    """
    if balance >= 0:
        return 0.0
    
    deficit_mm = abs(balance)
    return max(0.0, deficit_mm - forecast_rain)


def calculate_runtime_seconds(
    deficit_mm: float,
    precipitation_rate: float
) -> float:
    """Calculate runtime needed to cover a deficit.
    
    Args:
        deficit_mm: Moisture deficit in mm
        precipitation_rate: Sprinkler precipitation rate in mm/hour
        
    Returns:
        Runtime in seconds
    """
    if deficit_mm <= 0 or precipitation_rate <= 0:
        return 0.0
    
    runtime_hours = deficit_mm / precipitation_rate
    return runtime_hours * 3600


def update_zone_calculations(
    hass: HomeAssistant,
    config: Config,
    zone_config: ZoneConfig,
    zone_state: ZoneState,
) -> None:
    """Calculate and store runtime information for a zone.
    
    This is the main calculation function called by the coordinator.
    Results are stored directly in zone_state.calculated for entities to read.
    
    Args:
        hass: Home Assistant instance
        config: Integration configuration
        zone_config: Zone-specific configuration
        zone_state: Zone-specific state (will be mutated)
    """
    balance = zone_state.soil_moisture_balance
    forecast_rain = get_forecast_rain(hass, config)
    
    # Calculate effective deficit
    effective_deficit = calculate_effective_deficit(balance, forecast_rain)
    
    # Calculate required runtime
    required_runtime = calculate_runtime_seconds(
        effective_deficit, 
        zone_config.precipitation_rate
    )
    
    # Clamp to min/max limits for actual runtime
    if required_runtime > 0:
        clamped_runtime = max(
            zone_config.min_runtime, 
            min(required_runtime, zone_config.max_runtime)
        )
    else:
        clamped_runtime = 0.0
    
    # Ensure clamped runtime is never negative
    clamped_runtime = max(0.0, clamped_runtime)
    
    # Determine if zone can run and why
    can_run, reason = _evaluate_can_run(
        balance=balance,
        effective_deficit=effective_deficit,
        required_runtime=required_runtime,
        forecast_rain=forecast_rain,
        zone_config=zone_config,
        zone_state=zone_state,
    )
    
    # Store all calculated values in state
    calc = zone_state.calculated
    calc.effective_deficit_mm = effective_deficit
    calc.required_runtime_seconds = required_runtime
    calc.clamped_runtime_seconds = clamped_runtime
    calc.forecast_rain_mm = forecast_rain
    calc.can_run = can_run
    calc.reason = reason


def _evaluate_can_run(
    balance: float,
    effective_deficit: float,
    required_runtime: float,
    forecast_rain: float,
    zone_config: ZoneConfig,
    zone_state: ZoneState,
) -> tuple[bool, str]:
    """Evaluate whether a zone can run based on all constraints.
    
    Args:
        balance: Current soil moisture balance
        effective_deficit: Deficit after forecast rain
        required_runtime: Calculated runtime in seconds
        forecast_rain: Forecasted rain in mm
        zone_config: Zone configuration
        zone_state: Zone state
        
    Returns:
        Tuple of (can_run, reason)
    """
    # Check minimum interval has passed
    if zone_state.sprinkler_off_time is not None:
        time_since_off = (datetime.now() - zone_state.sprinkler_off_time).total_seconds()
        if time_since_off < zone_config.minimum_interval:
            return False, f"Minimum interval not met ({time_since_off:.0f}s < {zone_config.minimum_interval}s)"
    
    # No deficit at all
    if balance >= 0:
        return False, "No moisture deficit"
    
    # Forecast rain covers the deficit
    if effective_deficit <= 0:
        return False, f"Forecasted rain ({forecast_rain:.1f}mm) covers deficit"
    
    # Runtime too short
    if required_runtime < zone_config.min_runtime:
        return False, f"Runtime too short ({required_runtime:.0f}s < {zone_config.min_runtime}s minimum)"
    
    return True, "Ready to run"
