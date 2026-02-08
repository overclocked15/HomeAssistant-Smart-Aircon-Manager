# Services Reference

Smart Aircon Manager provides 12 services for controlling and managing the integration. All services are callable from automations, scripts, the Developer Tools UI, or dashboard buttons.

## Finding Your Config Entry ID

Many services require a `config_entry_id`. To find yours:

1. Go to **Developer Tools** > **States**
2. Search for any `smart_aircon_manager` entity
3. Click on it and look for `config_entry_id` in the attributes

Or: **Settings** > **Devices & Services** > **Smart Aircon Manager** > **Download Diagnostics** > look for `"entry_id"` in the JSON.

---

## System Services

### `smart_aircon_manager.force_optimize`

Immediately run an optimization cycle, bypassing the normal schedule.

| Field | Required | Default | Description |
|-------|----------|---------|-------------|
| `config_entry_id` | No | all | Runs all instances if not specified |

```yaml
service: smart_aircon_manager.force_optimize
data:
  config_entry_id: "abc123def456"
```

**Use case**: After manually adjusting settings, force an immediate recalculation instead of waiting for the next cycle.

---

### `smart_aircon_manager.reset_error_count`

Reset the error counter to zero.

| Field | Required | Default | Description |
|-------|----------|---------|-------------|
| `config_entry_id` | No | all | Resets all instances if not specified |

```yaml
service: smart_aircon_manager.reset_error_count
data:
  config_entry_id: "abc123def456"
```

**Use case**: Clear error count after resolving issues, so the error rate sensor starts fresh.

---

### `smart_aircon_manager.reset_smoothing`

Clear fan speed smoothing history. Fan speeds will jump to new calculated values on the next cycle.

| Field | Required | Default | Description |
|-------|----------|---------|-------------|
| `config_entry_id` | No | all | Resets all instances if not specified |

```yaml
service: smart_aircon_manager.reset_smoothing
data:
  config_entry_id: "abc123def456"
```

**Use case**: If fans seem "stuck" at certain speeds due to smoothing, reset to force immediate recalculation.

---

### `smart_aircon_manager.set_room_override`

Temporarily enable or disable automatic control for a specific room.

| Field | Required | Default | Description |
|-------|----------|---------|-------------|
| `config_entry_id` | Yes | - | Your config entry ID |
| `room_name` | Yes | - | Room name (e.g., "Living Room") |
| `enabled` | Yes | `true` | `true` to enable control, `false` to disable |

```yaml
service: smart_aircon_manager.set_room_override
data:
  config_entry_id: "abc123def456"
  room_name: "Bedroom"
  enabled: false
```

**Use case**: Temporarily exclude a room from optimization (e.g., guest room, room under maintenance).

---

### `smart_aircon_manager.reload`

Reload the integration to apply configuration changes.

```yaml
service: smart_aircon_manager.reload
```

---

## Quick Action Services

Quick actions apply temporary behavior changes across all rooms. They auto-expire after a configurable duration (except vacation mode which is manual on/off).

### `smart_aircon_manager.vacation_mode`

Enable energy-saving mode for extended absences. Reduces all fan speeds to 30% and widens the temperature deadband.

| Field | Required | Default | Description |
|-------|----------|---------|-------------|
| `config_entry_id` | Yes | - | Your config entry ID |
| `enabled` | No | `true` | `true` to enable, `false` to disable |

```yaml
# Enable vacation mode
service: smart_aircon_manager.vacation_mode
data:
  config_entry_id: "abc123def456"
  enabled: true

# Disable vacation mode
service: smart_aircon_manager.vacation_mode
data:
  config_entry_id: "abc123def456"
  enabled: false
```

**Behavior**: No auto-expiry. Must be manually disabled. Fan speeds capped at 30%, deadband widened to 2.0°C.

---

### `smart_aircon_manager.boost_mode`

Aggressive cooling/heating for rapid temperature adjustment. Multiplies all fan speeds by 1.5x (capped at 100%).

| Field | Required | Default | Description |
|-------|----------|---------|-------------|
| `config_entry_id` | Yes | - | Your config entry ID |
| `duration_minutes` | No | `30` | Duration in minutes (10-120) |

```yaml
service: smart_aircon_manager.boost_mode
data:
  config_entry_id: "abc123def456"
  duration_minutes: 30
```

**Behavior**: Auto-expires after duration. Enhanced compressor protection is bypassed for faster response.

---

### `smart_aircon_manager.sleep_mode`

Quieter operation for sleeping. Caps all fan speeds at 40% and adjusts the target temperature by ±1°C.

| Field | Required | Default | Description |
|-------|----------|---------|-------------|
| `config_entry_id` | Yes | - | Your config entry ID |
| `duration_minutes` | No | `480` | Duration in minutes (60-720, default 8 hours) |

```yaml
service: smart_aircon_manager.sleep_mode
data:
  config_entry_id: "abc123def456"
  duration_minutes: 480
```

**Behavior**: Auto-expires after duration. Fan speeds capped at 40% for quieter operation.

---

### `smart_aircon_manager.party_mode`

Equalize all rooms to a consistent temperature. Sets all fans to median speed (minimum 60%) for uniform comfort.

| Field | Required | Default | Description |
|-------|----------|---------|-------------|
| `config_entry_id` | Yes | - | Your config entry ID |
| `duration_minutes` | No | `120` | Duration in minutes (30-360, default 2 hours) |

```yaml
service: smart_aircon_manager.party_mode
data:
  config_entry_id: "abc123def456"
  duration_minutes: 120
```

**Behavior**: Auto-expires after duration. All rooms get equal airflow for consistent comfort across the house.

---

## Learning Services

### `smart_aircon_manager.enable_learning`

Enable adaptive learning to collect performance data and optionally apply adjustments.

| Field | Required | Default | Description |
|-------|----------|---------|-------------|
| `config_entry_id` | Yes | - | Your config entry ID |
| `mode` | No | `passive` | `passive` (collect data only) or `active` (apply adjustments) |

```yaml
service: smart_aircon_manager.enable_learning
data:
  config_entry_id: "abc123def456"
  mode: "active"
```

**Modes**:
- **passive**: Collects thermal mass, cooling efficiency, and convergence rate data without making adjustments. Safe to run indefinitely.
- **active**: Collects data AND applies learned adjustments to fan speeds, temperature bands, and balancing when confidence reaches the threshold (default 0.7).

---

### `smart_aircon_manager.disable_learning`

Disable learning. Existing learned data is preserved but no new data is collected or applied.

| Field | Required | Default | Description |
|-------|----------|---------|-------------|
| `config_entry_id` | Yes | - | Your config entry ID |

```yaml
service: smart_aircon_manager.disable_learning
data:
  config_entry_id: "abc123def456"
```

---

### `smart_aircon_manager.analyze_learning`

Force immediate analysis and update of learning profiles. Normally, analysis runs automatically during optimization cycles.

| Field | Required | Default | Description |
|-------|----------|---------|-------------|
| `config_entry_id` | No | all | Analyzes all instances if not specified |

```yaml
service: smart_aircon_manager.analyze_learning
data:
  config_entry_id: "abc123def456"
```

**Use case**: Check learning progress without waiting for the next automatic analysis cycle.

---

### `smart_aircon_manager.reset_learning`

Clear all learned data and start learning from scratch. Optionally reset only a specific room.

| Field | Required | Default | Description |
|-------|----------|---------|-------------|
| `config_entry_id` | No | all | Resets all instances if not specified |
| `room_name` | No | all rooms | Reset only this room's data |

```yaml
# Reset all rooms
service: smart_aircon_manager.reset_learning
data:
  config_entry_id: "abc123def456"

# Reset only one room
service: smart_aircon_manager.reset_learning
data:
  config_entry_id: "abc123def456"
  room_name: "Living Room"
```

**Use case**: After significant changes to your HVAC system (new equipment, renovations), reset learning so it adapts to the new characteristics.

---

## Automation Examples

### Vacation Mode When Away

```yaml
automation:
  - alias: "AC Vacation Mode When Away"
    trigger:
      - platform: state
        entity_id: input_boolean.vacation_mode
        to: "on"
    action:
      - service: smart_aircon_manager.vacation_mode
        data:
          config_entry_id: "abc123def456"
          enabled: true

  - alias: "AC Normal Mode When Home"
    trigger:
      - platform: state
        entity_id: input_boolean.vacation_mode
        to: "off"
    action:
      - service: smart_aircon_manager.vacation_mode
        data:
          config_entry_id: "abc123def456"
          enabled: false
```

### Boost Before Arriving Home

```yaml
automation:
  - alias: "Boost AC Before Arrival"
    trigger:
      - platform: zone
        entity_id: person.john
        zone: zone.home
        event: enter
    condition:
      - condition: numeric_state
        entity_id: sensor.smart_aircon_manager_house_avg_temperature
        above: 26
    action:
      - service: smart_aircon_manager.boost_mode
        data:
          config_entry_id: "abc123def456"
          duration_minutes: 30
```

### Sleep Mode at Bedtime

```yaml
automation:
  - alias: "Sleep Mode at Night"
    trigger:
      - platform: time
        at: "22:00:00"
    action:
      - service: smart_aircon_manager.sleep_mode
        data:
          config_entry_id: "abc123def456"
          duration_minutes: 480
```

### Force Optimization After Config Change

```yaml
automation:
  - alias: "Force Optimize After Climate Change"
    trigger:
      - platform: state
        entity_id: climate.smart_aircon_manager
        attribute: temperature
    action:
      - delay: "00:00:05"
      - service: smart_aircon_manager.force_optimize
        data:
          config_entry_id: "abc123def456"
```
