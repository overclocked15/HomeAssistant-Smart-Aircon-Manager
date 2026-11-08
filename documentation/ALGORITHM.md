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

## Damper Curve

Each room's zone position comes from how far the room is from its own target (Δ, in the direction being conditioned):

| Room | Position |
|------|----------|
| Needs conditioning, more than 0.5°C off | 50 + 50 × min(1, (Δ / 4)^0.8) % |
| Within ±0.5°C (the deadband) | 50% (baseline circulation) |
| Past its target by 0.5 to 1°C | 35% tapering to 22% |
| Past its target by 1 to 2°C, 2 to 3°C, 3°C or more | 22%, 12%, 5% (the overshoot tiers) |

Example positions:

| Off target by | +0.6 | +1 | +1.5 | +2 | +3 | +4 | -0.6 | -1 | -2 | -3 |
|---|---|---|---|---|---|---|---|---|---|---|
| Position | 60% | 66% | 72% | 78% | 89% | 100% | 32% | 22% | 12% | 5% |

The curve is steepest near the target (about 15 points per °C just outside the deadband) and flattens toward 100%. With learning active, adaptive bands move the 4°C saturation point (×1.2 for a slow room, ×0.8 for a fast one).

Heating mirrors cooling: a room below its target is the one that needs conditioning. In auto mode the direction is the one resolved for the cycle (see Auto Mode below).

Zones share one airflow, so what steers temperature is each room's position relative to the others, not the absolute numbers.

## Fan Speed Smoothing

Small changes are blended with the previous position to stop zones twitching:

```
smoothed = round(new_speed × factor + previous_speed × (1 - factor))
```

- **Factor** (default 0.7): higher = faster response, lower = smoother transitions
- **Threshold** (default 10): a change larger than this is applied at once

Example: from 50%, a new calculation of 55% (5 points, within the threshold) gives 54%; a new calculation of 80% (30 points) is applied immediately. At 30-second cycles a factor of 0.7 settles in about two cycles, so smoothing removes jitter rather than slowing control. Commands within 3 points of the zone's current position are skipped.

## Room Balancing

Balancing moves airflow from rooms that are ahead of their target to rooms that are behind.

**When it runs**: the spread between rooms (warmest minus coolest, each measured against its own target) is more than `target_room_variance` (default 1.5°C) and the house on average is within 1°C of target. It keeps running until the spread is back under two thirds of the setting (1.0°C by default) or the house average drifts more than 1.25°C off, so it can't switch on and off at the edge.

**Formula**:
```
balancing_bias = (room deviation - average deviation) × aggressiveness × 100
```

With the default aggressiveness of 0.2 that's 20 points per °C: a room hotter than the rest gets more air while cooling and less while heating.

**Minimum airflow**: no adjustment (balancing, learning, quick actions, humidity weighting, predictive control) takes a room below `min_airflow_percent` (default 15%), and none lifts a room the damper curve set lower on purpose (the 12% and 5% overshoot tiers).

### Adaptive Balancing (with learning)

When learning is active and confident, additional adjustments are made:
- **Learned bias**: up to ±10 points for a room that runs short of its target (or past it) day after day. It follows the room's mean shortfall over 24 hours, in "needs more air" terms for whichever mode is running, and fades once the room is fine
- **Relative drift rate**: rooms that gain heat (cooling) or lose heat (heating) faster than average at low airflow get extra balancing toward them
- **Room coupling**: rooms whose temperatures move together are balanced together

## AC Control Logic

Each room is judged against a **satisfaction threshold**: the global target, unless the room's own target (per-room override, schedule room target, occupancy setback or comfort relaxation) asks for *less* conditioning. That means a warmer room while cooling, or a cooler room while heating. A room asking for more conditioning than the global target is best-effort and never keeps the AC running on its own. The house "average" used below is the mean of each room's distance from its threshold. With no such rooms it is simply the average temperature minus the target.

### Turning AC On

The AC is turned on when `auto_control_main_ac` is enabled and either:
- The house average needs conditioning by `ac_turn_on_threshold` (default 1°C), or
- Any single room is 1.5× that threshold past its satisfaction threshold.

### Turning AC Off

The AC is turned off when:
- The house average is past the target by `ac_turn_off_threshold` (default 2°C), in the direction being conditioned,
- AND every room is satisfied (at or past its threshold).

This prevents premature turn-off when some rooms still need conditioning.

With **efficient operation** (efficiency mode, or battery-aware mode while running on the battery), the compressor rests once every room has been satisfied for 5 minutes:
- **Cooling:** fan-only by default, so air keeps moving and the main fan drops to low.
- **Heating:** switches off by default, because fan-only blows room-temperature air that feels like a draft.

It resumes at the normal turn-on thresholds. With humidity control on, the existing cool → dry → fan-only flow is left unchanged.

### Auto Mode

Auto mode decides each cycle whether the house needs cooling or heating, from the room temperatures:

- **Outlier rooms**: a single room more than 1.5× the turn-on threshold past its target sets the direction.
- **Hysteresis**: otherwise the house must pass the target by the deadband on the other side before the direction changes.
- **Reversal guard**: a running AC keeps its direction and is never reversed directly (dry counts as cooling).
- **Changeover**: a run ends once the house on average needs the other direction by the turn-on threshold (default 1°C), unless one room is still an outlier on the running side. After the minimum off-time the AC starts the other way. So heating starts about 1°C below target after cooling, instead of after the 2°C turn-off threshold, and one extreme room can't bounce the AC between modes.

### AC Temperature Setpoint

When `auto_control_ac_temperature` is enabled, the setpoint moves with house demand, both ways around the target:

```
offset = clamp(2 × house demand, -2°C, +4°C)      # +2°C cap with efficient operation
cooling:  setpoint = target - offset
heating:  setpoint = target + offset
```

While the house needs conditioning the unit is driven past the target (overdrive). Once the house is past the target the setpoint moves the other way (back-off), so the unit's own thermostat stops: a unit whose sensor reads 1°C warmer than the rooms settles them about 0.3°C under target instead of 1°C. Boost uses the full overdrive until the rooms reach their targets. With adaptive setpoint learning the gain is ×0.75 for a house that cools easily and ×1.25 for one that struggles; the target itself never shifts. It is refreshed even while every room sits inside the deadband. Values are rounded to the unit's `target_temp_step` (halves round up) and clamped to its `min_temp`/`max_temp`.

### Main Fan Speed

The main fan level comes from the same per-room distances, so a room kept warmer or cooler on purpose is satisfied at its own target:
- **Low**: rooms within 1°C of each other and the house within 0.5°C of its targets
- **High**: the house on average `main_fan_high_threshold` (default 2.5°C) short of its targets, or one room 3°C short with rooms 2°C apart
- **Medium**: the house on average `main_fan_medium_threshold` (default 1°C) short, or rooms 2°C apart
- **Low**: otherwise

A room past its target counts as at most one deadband past it, since more blower air can't help it. A level changes only once a threshold is passed by 0.2°C, so the fan doesn't flip at a boundary. Sleep holds it at low, boost raises it to high while rooms still need conditioning, and battery-aware saving levels cap it.

The speed is mapped onto the fan modes the unit actually offers: `mid`/`med` spellings, numbered speeds such as Daikin's 1–5, or quiet modes. A command is only sent when the mode changes. A fan mode picked on the manager's climate card holds until "auto" is picked again.

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

Uses the rate of change to act on where each room is heading.

**How it works**:
1. Track temperature history (last 10 readings per room)
2. Calculate the rate of change with weighted least squares (5-minute half-life) and outlier filtering
3. Project ahead: predicted = current + rate × `predictive_lookahead_minutes` × D, where D runs from 0.4 near the target to 0.7 at 3°C or more away (a conservative factor that keeps the projection modest)
4. Move the zone part of the way toward the position the damper curve gives for the predicted temperature: position = now + weight × (curve(predicted) - now), where the weight is `predictive_boost_factor` (default 0.3)

Rates under 0.03°C/min count as no trend (a single 0.1°C sensor step reads as about 0.01 to 0.02°C/min), so sensor noise doesn't move zones.

**Example**: room at 24°C, target 23°C, cooling at 0.15°C/min, 5-minute lookahead:
- Predicted: 24 - 0.15 × 5 × 0.5 = 23.6°C, where the curve gives 61% against 66% now
- With weight 0.3 the zone eases off from 66% to 65%; with weight 1.0, to 61%

## HVAC Mode Determination (with Humidity Control)

When humidity control is enabled, the system dynamically switches between modes:

**Priority order**:
1. **Temperature**: If temperature is outside deadband > cool or heat mode
2. **Humidity**: If temperature is OK but humidity is high > dry mode
3. **Both OK**: If temperature and humidity are within targets > fan_only mode

**Dry mode band**: dry mode starts when humidity reaches `dry_mode_humidity_threshold` (default 65%) or the target plus the humidity deadband, and keeps running until humidity is back down to `target_humidity` (default 60%). With a single switching point, humidity hovering at the threshold used to flip dry and fan-only every few minutes.

**Hysteresis**: Mode changes are throttled:
- Minimum time between changes: 300 seconds (default)
- Extra deviation required to override: 0.3°C (default)
- Exception: Exiting fan_only to cool/heat/dry is always immediate

"AC Mode Changed" alerts for dry and fan-only are sent at most once an hour each.

## Weather Adjustments

When enabled, outdoor temperature nudges the target in the direction that helps the current mode:

| Outdoor | Adjustment (before the influence factor) |
|---------|-----------|
| Above 30°C | -0.5°C |
| Above 25 up to 30°C | -0.25°C |
| 20 to 25°C | none |
| 15 up to 20°C | +0.25°C |
| Below 15°C | +0.5°C |

A fast outdoor trend adds -0.125°C per °C/hour of rise (only beyond ±1°C/hour, capped at ±0.5°C). Only adjustments that help the current mode apply (lower while cooling, higher while heating). The result is multiplied by `weather_influence_factor` (default 0.5) and rounded to 0.1°C: at defaults, at most 0.2°C from the tiers and 0.5°C with a fast trend. It is skipped while battery-aware mode is saving.

## Occupancy Control

When a room is detected as vacant (no motion for `vacancy_timeout` seconds):
- **Cooling mode**: Target raised by `vacant_room_setback` (room allowed to get warmer)
- **Heating mode**: Target lowered by `vacant_room_setback` (room allowed to get cooler)

This reduces energy usage for unoccupied rooms while maintaining comfort in occupied areas.

## Adaptive Learning

The learning system records each room's behavior and adjusts parameters from it.

### What is Learned

| Metric | How it is measured | Effect |
|--------|-------------|--------|
| **Thermal mass** (0 fast to 1 slow) | Median rate of change while the room is actively conditioned (more than 0.5°C off target, zone steady and at least half open), on a 0.2°C/min scale | Stretches (×1.2, slow room) or tightens (×0.8, fast room) the damper curve |
| **Cooling efficiency** (0 to 1) | Net cooling per minute per unit of zone opening while the room is more than 0.5°C above target, on a 0.1°C/min scale | Adjusts zone positions while cooling and, if enabled, the setpoint gain |
| **Convergence time** | Net progress toward the target over time while more than 0.5°C off | Scales predictive control |
| **Overshoot frequency** | Target crossings per day | Tunes smoothing (more overshoots, more damping) |
| **Relative drift** | Net heat gain or loss at low airflow, against the house average | Balancing |
| **Balancing bias** | Mean shortfall from target over 24 hours | Balancing (±10 points) |

Every interval counts, including ones where nothing changed, and each temperature change is paired with the zone position that was in place while it happened, so sensor noise and 0.1°C sensor steps average out.

### Learning Activation

1. Data collection begins when learning is enabled (one data point per room for each full pass while the AC runs)
2. Estimates start once a room has 50 data points; confidence (a recency-weighted sample count) reaches the default threshold of 0.7 at about 140 points
3. Adjustments apply in active mode once confidence passes the threshold
4. `learning_max_adjustment` (default 0.10) limits how far one hourly update moves a learned value

Profiles learned before v3.5.0 restart their estimates, because the old estimators saturated or measured sensor noise. Room coupling is kept.

### Room Coupling Detection

The system detects thermally coupled rooms (rooms that influence each other's temperature) using Pearson correlation analysis. Rooms with correlation >0.5 over 50+ overlapping data points are considered coupled. This information improves balancing accuracy.

## Quick Action Modes

Quick actions temporarily override normal behavior:

| Mode | What it does | Duration | Notes |
|------|-----------------|----------|-------|
| **Vacation** | Zones at 30% of computed position (never below minimum airflow) | Manual on/off | Widens deadband to 2.0°C; survives restarts |
| **Boost** | Full setpoint overdrive and main fan on high while rooms still need conditioning; zones opened in proportion, neediest fully open | 30 min default | Suspends comfort relaxation, battery saving and efficient operation |
| **Sleep** | Main fan held at low; comfort relaxed by 1°C (warmer while cooling, cooler while heating) | 8 hours default | Zones keep their positions: closing them with the blower running makes a ducted system louder, not quieter |
| **Party** | Every zone at the same opening (the median, at least 60%) | 2 hours default | Equal airflow to every room; suspends comfort relaxation |

Quick actions are checked each cycle and auto-expire when their duration elapses. Vacation's deadband is restored on exit, unless the user changed it during the mode. Sleep never edits the target temperature. Its 1°C relaxation is applied each cycle on top of schedules and per-room targets, so it can't flip auto mode to the opposite direction or outlive the mode. Quick actions never override a safety response: rooms paused by open-window detection and rooms in a critical-room emergency keep their airflow, and a critical-room emergency lifts sleep's main fan cap.

## Battery-Aware Mode

Optional, and vendor agnostic: it needs only a battery state-of-charge (%) sensor, from any integration. Each cycle it reads the charge (and battery power, if configured), learns, and picks a level:

| Level | When | What changes |
|-------|------|--------------|
| **normal** | Not running on the battery (charging, idle, full) | Nothing |
| **efficient** | Running on the battery | Efficient operation: the compressor rests when every room is satisfied (fan-only while cooling), and a gentler setpoint |
| **saving** | Projected charge at solar recovery is below reserve + buffer (`balanced`), or always on battery (`max_saving`) | + main fan capped at medium. Comfort relaxed: non-priority rooms by the full limit and dropped from AC decisions (priority rooms keep their target); without priority rooms, every room by half the limit |
| **max saving** | Projected well short (>10% below), or the battery within 3% of its reserve | + main fan capped at low, comfort relaxed up to the limit (priority rooms by half) |

Dehumidifying is never suppressed at any level. In humid weather a dry house at a slightly higher temperature feels better than a muggy one. Dry mode still engages below a relaxed target, because overcooling is judged against the user's real target.

**Projection**: SOC now minus the expected drain until the expected solar recovery. The drain comes from the learned per-hour overnight profile (separate for cooling and heating seasons), scaled by how tonight compares with it. Without a profile yet, the observed trend is used.

**What is learned** (from the SOC history, persisted in `.storage`):
- **Evening drain start:** when the battery starts draining.
- **Solar recovery:** when solar takes over in the morning (median of recent mornings; until 3 are known, sunrise from `sun.sun` plus the configured offset). A rise in charge before sunrise is treated as grid charging, not solar.
- **Drain profile:** the hourly overnight drain rate.
- **Safety buffer:** after a night that reached the reserve it grows, but only when saving earlier could have helped. After a night that ended comfortably it shrinks.

**Stability**:
- **Dwells:** levels rise after a 10-minute dwell and fall after a 45-minute dwell, and only once the projection clears its threshold by 10%.
- **Overdue recovery:** a cloudy morning is treated as solar about to arrive, not as another full night.
- **Stale data:** a charge reading more than 2 hours old makes the mode stand down to normal operation.

**Precedence**:
- **Safety and explicit comfort win:** a critical-room emergency, boost and party all suspend it.
- **Sleep:** sleep's relaxation and the battery relaxation combine by maximum, not sum.
- **Weather:** the weather adjustment, which only makes conditioning more aggressive, is skipped while saving.
- **Direction:** relaxation always widens the comfort band outward, so it can never cause the opposite mode, even in auto mode.

## Night Mode

When night mode is on, each cycle splits the rooms in two:

- **Night-mode rooms** (plus any room in a critical-room emergency) go through the normal pipeline: fan bands, smoothing, balancing, normalization, quick actions, and every AC-level decision (direction, on/off, mode, setpoint, main fan, efficient operation, battery relaxation).
- **Closed-off rooms** are still read but take no part in any decision. Their zone is set to the closed position after every other adjustment, so nothing reopens them.

A change in which rooms are closed (the switch, or a critical emergency starting or ending) forces a full pass on that cycle, even when every room is inside the deadband. A zone that was moving, unavailable or unknown during that pass is retried each cycle and sent a single command once it's ready. A room only settles once its command went through: a rejected command is retried with backoff (1, 2, 4 ... minutes, up to 30), which every pass respects: an optimization pass inside the backoff leaves that zone's command for later. Rooms changing state drop their smoothing history, learning baseline and any open-window pause, so a reopened room isn't smoothed from a speed set hours earlier and the night isn't learned as one long conditioning cycle. Closed rooms are also left out of the adaptive deadband's rate-of-change average.

Rooms switched out of use with their **In Use** switch join the closed-off set at any time of day, with the same machinery: closed zone, no part in any decision, the same retries and reopening, and critical-room emergencies still winning. With night mode on, the closed-off set is every room out of use plus every room that isn't a night-mode room. If every night-mode room is out of use, night mode stands aside. If every room is out of use, the exclusions are ignored, because there would be nothing left to manage.

Night mode is a hard version of battery-aware night zoning: battery zoning keeps air flowing to non-priority rooms and only stops them driving the AC, while night mode closes them. They compose: battery-aware mode sees only the night-mode rooms.

## Critical Room Protection

For rooms with critical temperature requirements (server rooms, wine cellars):

| Status | Condition | Action |
|--------|-----------|--------|
| Normal | Below warning threshold | Normal optimization |
| Warning | Within warning offset of critical temp | Alert sent |
| Critical | At or above critical temp (or at/below the freeze limit) | Emergency alert; the AC is turned on in the mode that serves the room |
| Recovering | Returning to the safe temperature | The AC stays on until safe |

While a room is critical or recovering, the optimizer works with the emergency:
- It never turns the AC off, and keeps it in the mode that serves the room.
- Dampers, setpoint and main fan follow the emergency's direction.
- Comfort relaxation and quick-action caps are suspended for that room.
- Turning the manager OFF leaves the AC running until the room recovers.
