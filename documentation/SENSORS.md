# Sensors & Entities Reference

Smart Aircon Manager creates a comprehensive set of entities for monitoring, control, and automation.

## Climate Entity

### `climate.smart_aircon_manager`

The main control entity for the integration.

| Attribute | Description |
|-----------|-------------|
| `current_temperature` | Average temperature across all rooms |
| `temperature` | Current target temperature |
| `hvac_mode` | Current mode: `auto`, `cool`, `off` |

**HVAC Modes**:
- `auto` - Management enabled (recommended)
- `cool` - Manual cooling mode
- `off` - Management disabled

**Actions**:
```yaml
# Set target temperature
service: climate.set_temperature
target:
  entity_id: climate.smart_aircon_manager
data:
  temperature: 23

# Enable/disable management
service: climate.set_hvac_mode
target:
  entity_id: climate.smart_aircon_manager
data:
  hvac_mode: "auto"
```

## Switch Entity

### `switch.smart_aircon_manager_manual_override`

Toggle to temporarily disable all automatic optimization.

| State | Behavior |
|-------|----------|
| `on` | Automation disabled, manual control of AC and fans |
| `off` | Automatic optimization active |

When manual override is on:
- Optimization cycles are skipped
- Sensors continue to update
- Learning data collection continues
- You have full manual control of all AC and fan entities

## Binary Sensor

### `binary_sensor.smart_aircon_manager_main_aircon_running`

Reports whether the main AC unit is currently running.

| State | Meaning |
|-------|---------|
| `on` | Main AC is running (heating, cooling, drying, or fan mode) |
| `off` | Main AC is off or unavailable |

## Per-Room Sensors

For each configured room, the integration creates these sensors (replace `{room}` with the lowercase, underscore-separated room name):

### `sensor.smart_aircon_manager_{room}_temperature_difference`

How far the room is from the target temperature.

| Attribute | Description |
|-----------|-------------|
| `state` | Temperature difference in °C (positive = above target, negative = below) |
| `current_temperature` | Current room temperature |
| `target_temperature` | Effective target for this room |
| `hvac_mode` | Current HVAC mode |

### `sensor.smart_aircon_manager_{room}_recommendation`

The system's calculated optimal fan speed for this room.

| Attribute | Description |
|-----------|-------------|
| `state` | Recommended fan speed (0-100%) |
| `room_name` | Room name |
| `current_temperature` | Current temperature |
| `target_temperature` | Target temperature |
| `deviation` | Temperature deviation from target |

### `sensor.smart_aircon_manager_{room}_fan_speed`

Current actual fan speed of the room's zone damper.

| Attribute | Description |
|-----------|-------------|
| `state` | Current position (0-100%) |
| `cover_entity` | Entity ID of the cover being controlled |
| `cover_state` | Cover entity state (open/closed/opening/closing) |

### `sensor.smart_aircon_manager_{room}_humidity` (if humidity sensor configured)

Current humidity reading for the room.

### `sensor.smart_aircon_manager_{room}_occupancy_status` (if occupancy control enabled)

| State | Meaning |
|-------|---------|
| `occupied` | Room is occupied |
| `vacant` | Room is vacant (setback applied) |
| `unknown` | No occupancy data available |

### Per-Room Learning Sensors (if learning enabled)

| Sensor | Description |
|--------|-------------|
| `sensor.smart_aircon_manager_{room}_learning_confidence` | Learning confidence level (0.0-1.0) |
| `sensor.smart_aircon_manager_{room}_thermal_mass` | Learned thermal mass (0.0-1.0, higher = slower to change) |
| `sensor.smart_aircon_manager_{room}_cooling_efficiency` | Learned cooling efficiency (0.0-1.0) |
| `sensor.smart_aircon_manager_{room}_data_points` | Number of learning data points collected |
| `sensor.smart_aircon_manager_{room}_convergence_rate` | Rate of temperature convergence |
| `sensor.smart_aircon_manager_{room}_smoothing_factor` | Current learned smoothing factor |
| `sensor.smart_aircon_manager_{room}_overshoot_rate` | Overshoot frequency (per day) |

## System-Wide Sensors

### Temperature & Status

| Sensor | Description |
|--------|-------------|
| `sensor.smart_aircon_manager_house_avg_temperature` | Average temperature across all rooms |
| `sensor.smart_aircon_manager_optimization_status` | Current status: maintaining, equalizing, cooling, etc. |
| `sensor.smart_aircon_manager_last_optimization_response` | Human-readable summary of last optimization decision |
| `sensor.smart_aircon_manager_effective_target_temperature` | Current effective target (after weather/schedule adjustments) |
| `sensor.smart_aircon_manager_room_temperature_variance` | Temperature spread across rooms (°C) |

### Timing

| Sensor | Description |
|--------|-------------|
| `sensor.smart_aircon_manager_last_data_update_time` | Timestamp of last sensor data poll |
| `sensor.smart_aircon_manager_last_optimization` | Timestamp of last optimization cycle |
| `sensor.smart_aircon_manager_next_optimization_time` | When the next optimization will run |
| `sensor.smart_aircon_manager_optimization_cycle_time` | How long the last cycle took (ms) |

### Diagnostics

| Sensor | Description |
|--------|-------------|
| `sensor.smart_aircon_manager_error_tracking` | Error count and details |
| `sensor.smart_aircon_manager_valid_sensors_count` | Number of working temperature sensors |
| `sensor.smart_aircon_manager_system_status_debug` | Overall health and debug info |
| `sensor.smart_aircon_manager_total_optimizations_run` | Total optimization cycles since startup |

### Main AC

| Sensor | Description |
|--------|-------------|
| `sensor.smart_aircon_manager_main_fan_speed_recommendation` | Recommended main AC fan speed (low/medium/high) |
| `sensor.smart_aircon_manager_ac_needs_running` | Whether the system thinks AC should be on |

### Weather (if enabled)

| Sensor | Description |
|--------|-------------|
| `sensor.smart_aircon_manager_outdoor_temperature` | Current outdoor temperature |
| `sensor.smart_aircon_manager_weather_adjustment` | Temperature adjustment applied from weather |

### Scheduling (if enabled)

| Sensor | Description |
|--------|-------------|
| `sensor.smart_aircon_manager_active_schedule` | Currently active schedule name (or "None") |

### Humidity (if enabled)

| Sensor | Description |
|--------|-------------|
| `sensor.smart_aircon_manager_hvac_mode_recommendation` | Recommended HVAC mode (cool/heat/dry/fan_only) |
| `sensor.smart_aircon_manager_house_average_humidity` | Average humidity across all rooms |
| `sensor.smart_aircon_manager_comfort_index` | Heat index combining temperature and humidity |

### Quick Actions

| Sensor | Description |
|--------|-------------|
| `sensor.smart_aircon_manager_quick_action_mode` | Active quick action mode (vacation/boost/sleep/party/off) |

**Attributes** (when a mode is active):
- `mode`: Current mode name
- `time_remaining`: Seconds until expiry (if applicable)
- `expiry_time`: Timestamp when mode expires

## Entity Naming Convention

All entities follow the pattern:
```
{platform}.smart_aircon_manager_{descriptor}
```

For per-room entities:
```
sensor.smart_aircon_manager_{room_name}_{sensor_type}
```

Room names are converted to lowercase with spaces replaced by underscores:
- "Living Room" becomes `living_room`
- "Master Bedroom" becomes `master_bedroom`

## Using Sensors in Automations

### Trigger on Temperature Deviation

```yaml
automation:
  - alias: "Alert if room too hot"
    trigger:
      - platform: numeric_state
        entity_id: sensor.smart_aircon_manager_living_room_temperature_difference
        above: 3
        for: "00:10:00"
    action:
      - service: notify.mobile_app
        data:
          title: "Temperature Alert"
          message: "Living room is {{ states('sensor.smart_aircon_manager_living_room_temperature_difference') }}°C above target!"
```

### Monitor System Health

```yaml
automation:
  - alias: "Alert on high error rate"
    trigger:
      - platform: numeric_state
        entity_id: sensor.smart_aircon_manager_error_tracking
        above: 10
    action:
      - service: notify.mobile_app
        data:
          title: "AC Manager Errors"
          message: "{{ states('sensor.smart_aircon_manager_error_tracking') }} errors detected. Check logs."
```

### Act on Quick Action Mode Changes

```yaml
automation:
  - alias: "Notify when quick action expires"
    trigger:
      - platform: state
        entity_id: sensor.smart_aircon_manager_quick_action_mode
        from: "boost"
        to: "off"
    action:
      - service: notify.mobile_app
        data:
          message: "Boost mode has ended. Returning to normal operation."
```
