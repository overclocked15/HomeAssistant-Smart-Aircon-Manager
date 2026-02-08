# Configuration Reference

Complete reference for all Smart Aircon Manager configuration options.

## Initial Setup

1. Go to **Settings** > **Devices & Services**
2. Click **Add Integration**
3. Search for **Smart Aircon Manager**
4. Follow the multi-step configuration wizard

## Core Settings

| Option | Type | Default | Range | Description |
|--------|------|---------|-------|-------------|
| `target_temperature` | float | `22` | 10-35 | Desired whole-house temperature (°C) |
| `temperature_deadband` | float | `0.5` | 0.1-5.0 | Acceptable deviation (±°C) before taking action |
| `update_interval` | float | `0.5` | 0.1-60 | Optimization frequency in minutes (0.5 = 30 seconds) |
| `hvac_mode` | select | `cool` | cool/heat/auto | Cooling, heating, or auto-detect from main climate entity |

## Entity Configuration

| Option | Type | Required | Description |
|--------|------|----------|-------------|
| `main_climate_entity` | entity | No | Your main AC climate entity (e.g., `climate.living_room_ac`) |
| `main_fan_entity` | entity | No | Main AC fan entity (can be the same as climate entity) |
| `room_configs` | list | Yes | List of room configurations (see Room Setup below) |

### Room Setup

Each room requires:

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `room_name` | string | Yes | Display name (e.g., "Living Room") |
| `temperature_sensor` | entity | Yes | Temperature sensor entity (e.g., `sensor.living_room_temperature`) |
| `cover_entity` | entity | Yes | Zone fan damper control (e.g., `cover.living_room_zone`) |
| `humidity_sensor` | entity | No | Humidity sensor for the room |
| `room_target_temperature` | float | No | Per-room target temperature override |

## AC Control

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `auto_control_main_ac` | bool | `false` | Automatically turn AC on/off based on temperature |
| `auto_control_ac_temperature` | bool | `false` | Automatically adjust AC temperature setpoint |
| `ac_turn_on_threshold` | float | `1.0` | °C above target to turn AC on |
| `ac_turn_off_threshold` | float | `2.0` | °C below target to turn AC off |
| `enable_notifications` | bool | `true` | Send notifications for important events |
| `notify_services` | list | `[]` | Notification service targets (empty = persistent_notification only) |

## Weather Integration

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `enable_weather_adjustment` | bool | `false` | Adjust target temperature based on outdoor conditions |
| `weather_entity` | entity | None | HA weather entity for outdoor data |
| `outdoor_temp_sensor` | entity | None | Outdoor temperature sensor (alternative to weather entity) |
| `weather_influence_factor` | float | `0.5` | How much outdoor temp influences target (0.0-1.0) |

**How it works**: On hot days, the target is lowered slightly for more aggressive cooling. On cold days, it's raised. The influence factor controls the magnitude.

## Time-Based Scheduling

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `enable_scheduling` | bool | `false` | Enable time-based temperature schedules |
| `schedules` | list | `[]` | List of schedule configurations |

### Schedule Format

Each schedule contains:

| Field | Type | Description |
|-------|------|-------------|
| `schedule_name` | string | Display name |
| `schedule_days` | select | Days to apply: monday-sunday, weekdays, weekends, all |
| `schedule_start_time` | time | Start time (HH:MM) |
| `schedule_end_time` | time | End time (HH:MM, supports cross-midnight) |
| `schedule_target_temp` | float | Target temperature during this schedule |
| `schedule_enabled` | bool | Enable/disable this schedule |

**Priority**: If multiple schedules overlap, specific day-of-week schedules take priority over "weekdays"/"weekends"/"all".

## Room Balancing

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `enable_room_balancing` | bool | `true` | Equalize temperatures across rooms |
| `target_room_variance` | float | `1.5` | Target max temperature variance between rooms (°C) |
| `balancing_aggressiveness` | float | `0.2` | How aggressively to balance (0.0-0.5) |
| `min_airflow_percent` | int | `15` | Minimum airflow to any room (%) |

## Fan Speed Smoothing

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `enable_fan_smoothing` | bool | `true` | Smooth fan speed transitions |
| `smoothing_factor` | float | `0.7` | Weight for new speed (0.7 = 70% new, 30% old) |
| `smoothing_threshold` | int | `10` | Only smooth changes smaller than this (percentage points) |

Large changes (above threshold) are applied immediately for fast response. Small changes are smoothed to prevent fan speed oscillation.

## Humidity Control

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `enable_humidity_control` | bool | `false` | Enable HVAC mode switching based on humidity |
| `target_humidity` | float | `60` | Target relative humidity (%) |
| `humidity_deadband` | float | `5` | Acceptable humidity range (±%) |
| `dry_mode_humidity_threshold` | float | `65` | Humidity % to activate dry mode |

**Mode priority** (when humidity control is enabled):
1. Temperature outside deadband > cool/heat mode
2. Temperature OK but humidity high > dry mode
3. Both OK > fan_only mode

## HVAC Mode Hysteresis

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `mode_change_hysteresis_time` | float | `300` | Minimum seconds between mode changes |
| `mode_change_hysteresis_temp` | float | `0.3` | Extra °C deviation required to override hysteresis |

Prevents rapid switching between cool/heat/dry/fan_only modes.

## Occupancy Control

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `enable_occupancy_control` | bool | `false` | Adjust temperature for vacant rooms |
| `occupancy_sensors` | dict | `{}` | Map of room_name to occupancy sensor entity |
| `vacant_room_setback` | float | `2.0` | °C to add/subtract from target for vacant rooms |
| `vacancy_timeout` | float | `300` | Seconds before considering room vacant |

**Behavior**: Vacant rooms get a setback (higher target in cool mode, lower in heat mode), reducing energy usage while maintaining occupied room comfort.

## Predictive Control

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `enable_predictive_control` | bool | `false` | Rate-of-change based proactive adjustments |
| `predictive_lookahead_minutes` | float | `5.0` | Minutes to project temperature ahead |
| `predictive_boost_factor` | float | `0.3` | Boost/reduction factor (0.0-1.0) |

**How it works**: Monitors the rate of temperature change and proactively adjusts fan speeds before the room actually reaches the threshold. Uses exponential decay dampening for accuracy.

## Compressor Protection

### Basic Protection

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `enable_compressor_protection` | bool | `true` | Prevent rapid AC cycling |
| `compressor_min_on_time` | float | `180` | Minimum seconds AC stays on |
| `compressor_min_off_time` | float | `180` | Minimum seconds AC stays off |

### Enhanced Compressor Protection

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `enable_enhanced_compressor_protection` | bool | `false` | Advanced mode-change protection |
| `compressor_undercool_margin` | float | `0.5` | °C below target before switching to fan (cooling) |
| `compressor_overheat_margin` | float | `0.5` | °C above target before switching to fan (heating) |
| `min_mode_duration` | float | `600` | Minimum seconds in compressor mode |
| `min_compressor_run_cycles` | int | `3` | Minimum optimization cycles before mode change |

**Recommended presets**:
- **Conservative**: margins 0.3°C, duration 300s - minimal temperature impact
- **Balanced** (default): margins 0.5°C, duration 600s - good protection/comfort balance
- **Aggressive**: margins 1.0°C, duration 900s - maximum compressor protection

## Adaptive Learning

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `enable_learning` | bool | `false` | Enable data collection and adaptive learning |
| `learning_mode` | select | `passive` | passive (collect only) or active (apply adjustments) |
| `learning_confidence_threshold` | float | `0.7` | Minimum confidence to apply learning (0.0-1.0) |
| `learning_max_adjustment` | float | `0.10` | Maximum parameter adjustment per update (10%) |

### Adaptive Features (require learning enabled + active mode)

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `enable_adaptive_bands` | bool | `true` | Adjust temperature bands based on learned thermal mass |
| `enable_adaptive_efficiency` | bool | `true` | Adjust fan speeds based on learned cooling efficiency |
| `enable_adaptive_predictive` | bool | `true` | Adjust predictive boost based on learned convergence rate |
| `enable_adaptive_ac_setpoint` | bool | `false` | Adjust AC setpoint based on house-wide efficiency |
| `enable_adaptive_balancing` | bool | `true` | Apply learned biases to room balancing |
| `enable_room_coupling_detection` | bool | `true` | Detect thermally coupled rooms |

**Activation requirements**:
1. Enable learning: `enable_learning: true`
2. Set mode to active: `learning_mode: "active"`
3. Wait for data collection (200+ points, about 1.5-2 hours)
4. Features auto-activate when confidence reaches the threshold (default 0.7)

## Critical Room Protection

Configure rooms that must never exceed a temperature threshold (e.g., server rooms, wine cellars):

| Option | Type | Description |
|--------|------|-------------|
| `critical_rooms` | dict | Map of room_name to critical config |
| `critical_temp_max` | float | Maximum allowed temperature |
| `critical_temp_safe` | float | Temperature to recover to |
| `critical_warning_offset` | float | °C before critical to send warning (default: 2.0) |
| `critical_notify_services` | list | Notification targets for critical alerts |

## Room Overrides

Override automation for specific rooms without disabling the whole system:

```yaml
room_overrides:
  bedroom: false    # Disable automation for bedroom
  kitchen: true     # Keep automation for kitchen (default)
```

Or use the service call:
```yaml
service: smart_aircon_manager.set_room_override
data:
  config_entry_id: "your_entry_id"
  room_name: "bedroom"
  enabled: false
```
