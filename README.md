# Adaptive Irrigation

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/custom-components/hacs)

A Home Assistant integration that tracks soil moisture balance for irrigation zones using weather data and evapotranspiration calculations.

## Quick Overview

This integration monitors your irrigation zones by tracking a **soil moisture balance** where:
- **0mm** = optimal moisture
- **Negative values** = needs water (deficit)
- **Positive values** = too wet (excess)

It automatically:
- ✅ Adds rainfall from your weather station
- ✅ Tracks sprinkler runtime and water applied
- ✅ Subtracts daily evapotranspiration (ET) at midnight
- ✅ Calculates exact runtime needed to reach optimal moisture

---

## Inputs (Required Configuration)

### Weather Station Sensors
- **Temperature** (°C) - Required for all ET calculations
  - Valid range: -50°C to 60°C
- **Relative Humidity** (%) - Required for all ET calculations
  - Valid range: 0% to 100%
- **Precipitation** (mm) - Cumulative rainfall total
  - Valid range: 0mm to 500mm
  - Rainfall increases >200mm/day are rejected as sensor errors
- **Wind Speed** (km/h) - Optional, enables Penman-Monteith method
  - Valid range: 0 km/h to 200 km/h
- **Solar Radiation** (W/m²) - Optional, enables Priestley-Taylor or Penman-Monteith
  - Valid range: 0 W/m² to 1500 W/m²
- **Pressure** (hPa) - Optional, improves accuracy
  - Valid range: 800 hPa to 1100 hPa

**Sensor Data Validation:**
- Invalid sensor readings outside the ranges above are automatically filtered out and logged as warnings
- Both real-time updates and historical database queries validate all sensor data
- This prevents obviously erroneous values (sensor glitches, connectivity issues) from corrupting ET calculations

**ET Method Auto-Selection:**
- Wind + Solar → **Penman-Monteith** (most accurate)
- Solar only → **Priestley-Taylor** (good accuracy)
- Neither → **Hargreaves** (temperature-based)

### Location Settings
- **Latitude/Longitude** - For ET calculations (defaults to HA location)
- **Elevation** (m) - For ET calculations

### Zone Configuration (per zone)
- **Zone Name** - Friendly name
- **Sprinkler/Valve Entity** - Switch or valve to monitor
- **Precipitation Rate** (mm/hour) - How fast your sprinkler adds water
- **Crop Coefficient (Kc)** - ET adjustment factor (0.4-2.0, default 1.0)

---

## Outputs (Generated Entities)

For each configured zone:

### `number.<zone_name>_soil_moisture_balance`
**Soil Moisture Balance** (mm)
- Shows current moisture balance relative to optimal
- 0mm = optimal, negative = deficit, positive = excess
- Can be manually adjusted if needed
- Updates automatically with rain, irrigation, and ET

### `sensor.<zone_name>_required_runtime`
**Required Runtime** (seconds)
- Calculates exact sprinkler runtime needed to reach 0mm balance
- Returns 0 if balance is already optimal or positive
- Formula: `(deficit_mm / precipitation_rate_mm_per_hour) × 3600`

---

## Features

- **Evapotranspiration Calculation**: Uses the [pyet](https://github.com/pyet-org/pyet) library to calculate daily water loss through evapotranspiration
- **Multiple ET Methods**: Auto-selects best method (Penman-Monteith, Priestley-Taylor, or Hargreaves) based on available sensors
- **Historical Data Analysis**: Queries Home Assistant's database for previous day's weather data to calculate accurate daily averages
- **Real-time Rainfall Tracking**: Automatically adds precipitation to soil moisture balance as it occurs
- **Automatic Irrigation Tracking**: Monitors sprinkler runtime and calculates water added based on precipitation rate
- **Multi-Zone Support**: Configure unlimited irrigation zones with individual settings
- **Crop Coefficients**: Adjust ET calculations per zone based on plant type
- **Soil Moisture Balance**: Creates a number entity for each zone showing moisture balance in mm where:
  - 0mm = optimal moisture level
  - Positive values = excess moisture (too wet)
  - Negative values = moisture deficit (too dry)
- **User Adjustable**: Balance values can be manually overridden at any time

## How It Works

### Soil Moisture Tracking

The integration maintains a soil moisture balance (in mm) for each irrigation zone, where 0mm represents optimal moisture:

1. **Rainfall Addition**: When precipitation is detected from your weather station, it's added to all zones immediately (moves balance toward positive/excess)
2. **Irrigation Addition**: When a sprinkler/valve turns on, the integration tracks runtime and calculates water added based on:
   - Runtime duration
   - Configured precipitation rate (mm/hour)
   - Water added moves balance toward positive/excess
3. **ET Subtraction**: At midnight each day, evapotranspiration is calculated using your weather data and subtracted from each zone's balance (moves balance toward negative/deficit)

### ET Calculation

The integration uses **historical weather data from Home Assistant's database** to calculate reference evapotranspiration (ET₀):

- At midnight, the integration queries the recorder database for all sensor states from the previous 24 hours
- Daily averages are calculated from all recorded state changes
- These averages are used for ET computation using the pyet library
- This provides highly accurate ET values based on actual recorded data, not sampled snapshots
- **Temperature** and **Humidity** are required for all methods
- **Wind Speed**, **Solar Radiation**, and **Pressure** improve accuracy for Penman-Monteith
- Each zone applies a **crop coefficient (Kc)** to adjust ET₀ for specific plant types

ET is calculated once per day at midnight using the previous day's weather data.

## Installation

### Via HACS (Recommended)

1. Add this repository as a custom repository in HACS
2. Search for "Adaptive Irrigation" in HACS
3. Click Install
4. Restart Home Assistant

### Manual Installation

1. Copy the `custom_components/adaptive-irrigation` directory to your Home Assistant `custom_components` directory
2. Restart Home Assistant

## Configuration

The integration is configured through the Home Assistant UI:

1. Go to **Settings** → **Devices & Services**
2. Click **+ Add Integration** and search for "Adaptive Irrigation"
3. Follow the configuration steps:

### Step 1: Weather Sensors

Configure your local weather station entities:

- **Temperature Sensor** (Required): Current temperature
- **Humidity Sensor** (Required): Current relative humidity
- **Precipitation Sensor** (Required): Cumulative precipitation (the integration tracks increases)
- **Wind Speed Sensor** (Optional): Enables Penman-Monteith ET method
- **Solar Radiation Sensor** (Optional): Enables Priestley-Taylor or Penman-Monteith methods
- **Pressure Sensor** (Optional): Improves ET calculation accuracy (hPa)

The integration automatically selects the best ET calculation method based on configured sensors.

### Step 2: Location Settings

- **Latitude/Longitude/Elevation**: Used for ET calculations (defaults to your HA location)

### Step 3: Irrigation Zones

Configure each irrigation zone:

- **Zone Name**: Friendly name for the zone
- **Sprinkler/Valve Entity**: The switch/valve entity that controls irrigation
- **Precipitation Rate**: How fast your sprinkler adds water (mm/hour)
- **Crop Coefficient (Kc)**: Adjustment factor for ET (default: 1.0)
  - Grass: 0.8-1.0
  - Vegetables: 0.7-1.05
  - Shrubs: 0.5-0.7
  - Trees: 0.4-1.2

## Entities

The integration creates the following entities:

### Number Entities

For each zone:
- `number.<zone_name>_soil_moisture_balance` - Current soil moisture balance in mm
  - 0mm = optimal
  - Positive = too wet (excess moisture)
  - Negative = too dry (moisture deficit)
  - Can be manually adjusted by the user

### Sensor Entities

For each zone:
- `sensor.<zone_name>_required_runtime` - Required sprinkler runtime in seconds to reach optimal moisture (0mm balance)
  - Automatically calculated based on current balance and precipitation rate
  - Returns 0 if balance is already optimal or excess

## Services

### `adaptive_irrigation.calculate_et`

Force immediate calculation and application of evapotranspiration for testing purposes.

**Data:**
- `entry_id` (optional): Specific config entry ID to calculate ET for. If omitted, calculates for all entries.

**Example:**
```yaml
# Calculate ET for all zones
service: adaptive_irrigation.calculate_et

# Calculate ET for specific integration instance
service: adaptive_irrigation.calculate_et
data:
  entry_id: "01234567890abcdef"
```

This is useful for testing ET calculations without waiting for midnight, or manually triggering ET calculations on demand.

---

## Example Automation

Use the soil moisture balance to automate irrigation when plants need water:

```yaml
automation:
  - alias: "Water Front Lawn when soil is dry"
    trigger:
      - platform: numeric_state
        entity_id: number.front_lawn_soil_moisture_balance
        below: -20  # Water when 20mm deficit
    condition:
      - condition: time
        after: "05:00:00"
        before: "08:00:00"
    action:
      - service: switch.turn_on
        target:
          entity_id: switch.front_lawn_sprinkler
      - delay:
          seconds: "{{ states('sensor.front_lawn_required_runtime') | int }}"
      - service: switch.turn_off
        target:
          entity_id: switch.front_lawn_sprinkler
```

This automation will run the sprinkler for exactly the calculated time needed to reach optimal moisture!

## Tips & Best Practices

1. **Calibrate Precipitation Rate**: 
   - Run your sprinkler for a known time
   - Use rain gauges or collection containers to measure actual water depth
   - Calculate: `precipitation_rate = depth_mm / time_hours`

2. **Understand Balance Values**:
   - 0mm = Optimal moisture
   - -10mm = Slightly dry, may need water soon
   - -30mm = Definitely needs watering
   - +10mm = Slightly wet from recent rain/watering
   - +30mm = Very wet, no watering needed

3. **Choose the Right ET Method**:
   - Use Penman-Monteith if you have wind and solar radiation sensors
   - Use Hargreaves for minimal sensor setups
   - Results are daily averages, specific to your location

4. **Adjust Crop Coefficients**:
   - Start with standard values from FAO-56 tables
   - Fine-tune based on observed plant health and irrigation needs

5. **Manual Override Available**:
   - If balance seems off, you can manually adjust it in the UI
   - Useful after initial setup or unusual weather events

## Disclaimer

**Use at Your Own Risk**

This software is provided "as is," without any warranty. The authors are not liable for any damages or losses arising from use of this software.

Irrigation systems can cause property damage if misconfigured. It is your responsibility to ensure your system is installed and configured safely and in compliance with local regulations.

## License

GPL-3.0 License - see LICENSE file for details

## Credits

- Evapotranspiration calculations powered by [pyet](https://github.com/pyet-org/pyet)
- Inspired by [ZeroGrid](https://github.com/mike-debney/zerogrid) integration architecture
