# Algorithm & How It Works

Deep dive into how Smart Aircon Manager makes decisions.

## Overview

The system runs an optimization cycle every 30 seconds (configurable). Each cycle:

1. Reads all temperature sensors
2. Calculates optimal fan speeds for each room
3. Applies smoothing to prevent oscillation
4. Applies predictive adjustments (if enabled)
5. Balances temperatures across rooms
6. Determines if AC should be on/off
7. Sets AC temperature and fan speed
8. Applies fan speeds to zone dampers

## 8-Band Temperature Logic

Fan speeds are calculated based on how far each room's temperature is from the target, using an 8-band system.

### Cooling Mode (room above target)

| Deviation | Fan Speed | Purpose |
|-----------|-----------|---------|
| 4°C+ above | 100% | Maximum cooling |
| 3-4°C | 90% | Aggressive cooling |
| 2-3°C | 75% | Strong cooling |
| 1.5-2°C | 65% | Good cooling |
| 1-1.5°C | 55% | Moderate cooling |
| 0.7-1°C | 45% | Gentle cooling |
| 0.5-0.7°C | 40% | Minimal cooling |
| Within ±0.5°C | 50% | Baseline circulation |

### Cooling Mode (room below target - overshot)

| Deviation | Fan Speed | Purpose |
|-----------|-----------|---------|
| 3°C+ below | 5% | Near shutdown |
| 2-3°C | 12% | Minimal airflow |
| 1-2°C | 22% | Reduced cooling |
| 0.7-1°C | 30% | Gentle reduction |
| 0.5-0.7°C | 35% | Slight reduction |

### Heating Mode

Same logic as cooling, but inverted: rooms below target get more fan, rooms above target get less.

### Auto Mode

Detects from the main climate entity whether cooling or heating is needed.

## Fan Speed Smoothing

To prevent fan speed oscillation (rapid changes every cycle), a smoothing algorithm is applied:

```
smoothed_speed = (new_speed × factor) + (previous_speed × (1 - factor))
```

- **Factor** (default 0.7): Higher = faster response, lower = smoother transitions
- **Threshold** (default 10): Changes larger than this skip smoothing for fast response

Example: If current speed is 50% and calculated speed is 80%:
- Change = 30% (above threshold of 10) > applied immediately
- If calculated speed was 55%, change = 5% (below threshold) > smoothed to ~53.5%

## Room Balancing

When temperatures differ between rooms, the balancing algorithm adjusts fan speeds to equalize them.

**How it works**:
1. Calculate the average temperature across all rooms
2. For each room, calculate deviation from the average
3. Adjust fan speed up (for rooms further from target) or down (for rooms closer to target)
4. The adjustment magnitude is controlled by `balancing_aggressiveness` (default 0.2)

**Formula**:
```
balancing_bias = deviation_from_avg × aggressiveness × 100
```

**Constraints**:
- Minimum airflow is always maintained (default 15%)
- Balancing only activates when the house average is near the target
- Very hot/cold rooms are excluded from balancing to prioritize direct cooling/heating

### Adaptive Balancing (with learning)

When learning is active and confident, additional adjustments are made:
- **Learned balancing bias**: Corrects for rooms that consistently overshoot/undershoot
- **Relative convergence rate**: Rooms that heat/cool faster get less aggressive balancing
- **Room coupling**: Thermally connected rooms (shared walls/open doors) are balanced together

## AC Control Logic

### Turning AC On

The AC is turned on when:
- `auto_control_main_ac` is enabled
- Average temperature exceeds target by `ac_turn_on_threshold` (default 1°C)
- In cool mode: any room is significantly above target
- In heat mode: any room is significantly below target

### Turning AC Off

The AC is turned off when:
- Average temperature is below target by `ac_turn_off_threshold` (default 2°C)
- AND the maximum room temperature is at or below the target
- This prevents premature turn-off when some rooms still need conditioning

### AC Temperature Setpoint

When `auto_control_ac_temperature` is enabled, the system calculates the optimal AC setpoint:

**Cooling**:
- Aggressive (far from target): 19°C
- Moderate: 21°C
- Maintenance (near target): 23°C

**Heating**:
- Aggressive (far from target): 25°C
- Moderate: 23°C
- Maintenance (near target): 21°C

### Main Fan Speed

The main AC fan speed is set based on overall need:
- **Low**: All rooms near target (variance <= 1°C, avg deviation <= 0.5°C)
- **High**: Significant need (avg deviation >= 2.5°C OR max deviation >= 3°C)
- **Medium**: All other conditions

## Compressor Protection

### Basic Protection

Prevents rapid AC on/off cycling that damages compressors:
- Minimum on time: 180 seconds (default)
- Minimum off time: 180 seconds (default)
- Timestamps are persisted across HA restarts

### Enhanced Protection

Reduces mode change frequency (cool/heat to fan_only):

1. **Undercool/Overheat Margins**: In cooling mode, the system continues cooling past the target by the margin amount before switching to fan. This creates longer, less frequent cooling cycles.

2. **Minimum Mode Duration**: Once in a compressor mode (cool/heat), stays there for at least the configured duration regardless of temperature.

3. **Minimum Run Cycles**: Requires a minimum number of optimization cycles in compressor mode before switching.

## Predictive Control

Uses rate-of-change to anticipate temperature trends and act proactively.

**How it works**:
1. Track temperature history (last 10 readings per room)
2. Calculate rate of change using linear regression with outlier filtering
3. Project temperature forward by `predictive_lookahead_minutes`
4. Apply exponential decay dampening (accounts for Newton's law of cooling)
5. Boost or reduce fan speed based on predicted deviation

**Example**: Room at 23°C, target 22°C, cooling at -0.2°C/min:
- Linear prediction: 23 + (-0.2 × 5) = 22°C in 5 minutes
- Dampened prediction: ~22.5°C (rate slows as target approaches)
- Action: Reduce fan speed proactively to prevent overcooling

## HVAC Mode Determination (with Humidity Control)

When humidity control is enabled, the system dynamically switches between modes:

**Priority order**:
1. **Temperature**: If temperature is outside deadband > cool or heat mode
2. **Humidity**: If temperature is OK but humidity is high > dry mode
3. **Both OK**: If temperature and humidity are within targets > fan_only mode

**Hysteresis**: Mode changes are throttled:
- Minimum time between changes: 300 seconds (default)
- Extra deviation required to override: 0.3°C (default)
- Exception: Exiting fan_only to cool/heat is always immediate (temperature priority)

## Weather Adjustments

When enabled, outdoor temperature influences the target:

- **Hot weather** (>30°C outdoor): Target lowered by up to `weather_influence_factor × 2°C`
- **Cold weather** (<10°C outdoor): Target raised by up to `weather_influence_factor × 2°C`
- **Mild weather** (10-30°C): No adjustment

The adjustment scales linearly with how extreme the outdoor temperature is.

## Occupancy Control

When a room is detected as vacant (no motion for `vacancy_timeout` seconds):
- **Cooling mode**: Target raised by `vacant_room_setback` (room allowed to get warmer)
- **Heating mode**: Target lowered by `vacant_room_setback` (room allowed to get cooler)

This reduces energy usage for unoccupied rooms while maintaining comfort in occupied areas.

## Adaptive Learning

The learning system collects data on each room's behavior and adjusts parameters accordingly.

### What is Learned

| Metric | Description | Effect |
|--------|-------------|--------|
| **Thermal mass** | How quickly the room changes temperature (0.0-1.0) | Adjusts temperature band widths |
| **Cooling efficiency** | How effectively the room responds to fan changes (0.0-1.0) | Adjusts fan speed magnitude |
| **Convergence rate** | Time to reach target temperature | Adjusts predictive boost |
| **Overshoot frequency** | How often the room overshoots the target | Adjusts smoothing factor |
| **Balancing bias** | Consistent over/under-shoot tendency | Adjusts room balancing |

### Learning Activation

1. Data collection begins immediately when learning is enabled
2. Requires 200+ data points per room (about 1.5-2 hours at 30s intervals)
3. Confidence must reach the threshold (default 0.7) before adjustments are applied
4. All adjustments are bounded to prevent extreme changes

### Room Coupling Detection

The system detects thermally coupled rooms (rooms that influence each other's temperature) using Pearson correlation analysis. Rooms with correlation >0.5 over 50+ overlapping data points are considered coupled. This information improves balancing accuracy.

## Quick Action Modes

Quick actions temporarily override normal behavior:

| Mode | Fan Speed Effect | Duration | Notes |
|------|-----------------|----------|-------|
| **Vacation** | All fans to 30% | Manual on/off | Widens deadband to 2.0°C |
| **Boost** | All fans × 1.5 (max 100%) | 30 min default | Bypasses enhanced compressor protection |
| **Sleep** | All fans capped at 40% | 8 hours default | Target adjusted ±1°C |
| **Party** | All fans to median (min 60%) | 2 hours default | Equalizes all rooms |

Quick actions are checked each cycle and auto-expire when their duration elapses. Original settings are restored on expiry, unless the user manually changed settings during the mode.

## Critical Room Protection

For rooms with critical temperature requirements (server rooms, wine cellars):

| Status | Condition | Action |
|--------|-----------|--------|
| Normal | Below warning threshold | Normal optimization |
| Warning | Within warning offset of critical temp | Alert sent, increased cooling |
| Critical | At or above critical temp | Emergency alert, maximum cooling |
| Recovering | Cooling back to safe temperature | Sustained cooling until safe |
