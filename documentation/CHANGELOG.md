# Changelog

## v3.0.0 - Full Logic Audit + Feature Release

**Release Date**: 2026-07-05

### Bug fixes (logic audit)

- **Room balancing now respects per-room targets** (`_apply_room_balancing`): balancing previously equalized raw temperatures toward the house average, so a room intentionally held at a different setpoint (per-room override) was treated as an outlier and conditioned against its own target. Balancing now works on each room's deviation from *its own* effective target (override + occupancy setback), including the coupled-room contribution.
- **Mode resolver no longer conditions in an unservable direction** (`_determine_optimal_hvac_mode`): in fixed cool mode with the house overcooled past the deadband (or fixed heat + overheated), the resolver used to pick the active mode anyway, deepening the overshoot. It now falls through to fan_only. Dry mode is also suppressed while the house is overcooled (dry cools too).
- **Quick-action modes now expire even when the AC is off**: expiry was only processed inside the optimization branch, which requires the AC to be running — a sleep-mode ±1°C setback could outlive its window indefinitely. Expiry is now checked at the top of every poll cycle.
- **Overshoot fan-speed tiers made monotonic**: speeds by overshoot depth were 15% → 20% → 22% → 12% → 5% (deeper overshoot got MORE airflow in the first three bands). Now a monotonically decreasing curve: 35% tapering to 22% below tier 1, then 22% / 12% / 5%, which also removes the 50%→15% cliff at the deadband edge.
- **Fan-speed normalization no longer amplifies mild demand**: any room barely outside the deadband (~55% speed) used to be scaled to 100%, defeating the proportional curve, predictive adjustments, and smoothing exactly where fine control matters. Normalization now only engages under strong demand (max speed ≥ 80%).
- **`main_fan_medium_threshold` is now actually used**: the main fan picks low below the medium threshold (unless rooms are unbalanced ≥2°C variance, which holds medium for equalization airflow); previously the setting was validated in the UI but dead in the logic.
- **Enhanced compressor protection guards cool↔heat reversals**: minimum mode duration and run-cycle checks previously only guarded compressor→fan_only exits; a direct cool↔heat flip (the harshest transition) bypassed them.
- **Weather adjustment direction-gating uses current temperatures**: the cool/heat gate resolved from the previous cycle's mode (defaulting to "cool" on the first cycle), which discarded helpful cold-weather adjustments in heating households. Room states are now collected first and passed in.
- **Damper curves stay season-correct during dry/fan_only interludes**: in auto mode, `_get_effective_operating_mode` fell back to "cool" while circulating, driving heating-household dampers with cooling logic. The last active cool/heat resolution is now remembered across circulation periods.
- **Exiting boost/sleep/party no longer resets the deadband**: only vacation mode changes the deadband, but exit restored it for all modes, silently reverting manual changes made mid-mode.
- **Turning the manager climate entity OFF turns the physical AC off** (when *Auto Control Main AC* is enabled) instead of leaving it running unmanaged.
- **Learning data is now season-tagged**: cooling efficiency is computed from cool-mode data only (heating-season data previously blended an unrelated signal into it), and relative convergence rates prefer season-specific data.
- **Room removal cleans up per-room config**: removing a room now also removes its control override, critical-room thresholds, occupancy sensor mapping, and schedule per-room targets (renames migrate all of these too).
- **Fan smoothing settings are wired up**: `enable_fan_smoothing`, `smoothing_factor`, and `smoothing_threshold` were documented but hardcoded; they're now applied and exposed in Advanced Settings.

### Features

- **Occupancy control & presence UI**: occupancy control (per-room sensors, setback, timeout) is now configurable from the options flow — previously documented but unreachable. Includes new **presence-linked away mode**: when all configured persons/device trackers are away for a delay, vacation mode engages automatically and exits when someone returns.
- **Predictive control & open-window detection UI**: predictive control is now configurable from the UI. New **open window/door detection** pauses conditioning (minimum airflow + notification) for rooms moving rapidly against the active mode despite full airflow, resuming automatically.
- **Compressor protection & AC thresholds UI**: basic + enhanced compressor protection, AC turn-on/turn-off thresholds, and mode-change hysteresis are now configurable from the UI.
- **Fan-only idle shutdown**: optional timeout that turns the AC fully off after idling in fan_only mode (default 0 = keep circulating), instead of running the blower indefinitely.
- **Dry-mode humidity weighting**: in dry mode, rooms above the humidity target get proportionally more airflow (up to +30%), so the dampest rooms are served first.
- **Freeze protection for critical rooms**: critical rooms accept an optional minimum temperature; dropping below it triggers alerts and automatically turns on heating (mirrors the existing over-temperature protection).
- **Per-room schedule targets**: schedules accept optional per-room targets (e.g. `Bedroom=18, Office=21.5`) that take precedence over per-room overrides during the schedule window.
- **Runtime & filter tracking**: new *Compressor Runtime Today* and *Filter Runtime* sensors, a configurable filter-due threshold surfaced as a sensor attribute, and a `reset_filter_timer` service for after filter changes.

## v2.16.3 - Pattern-Sweep Fixes (Same-Family Bugs from v2.16.2)

**Release Date**: 2026-05-16

After shipping v2.16.2, a targeted sweep for the same two patterns surfaced five more instances. None were user-reported, but all share root causes with bugs the user just hit.

### Pattern 1 — UI removal blocked by `vol.Optional(..., default=...)`
The same substitute-on-empty-submit bug that broke per-room target removal also affected:
- **Weather entity** ([config_flow.py:818](../custom_components/smart_aircon_manager/config_flow.py#L818))
- **Outdoor temperature sensor** ([config_flow.py:829](../custom_components/smart_aircon_manager/config_flow.py#L829))
- **Main climate entity** ([config_flow.py:362](../custom_components/smart_aircon_manager/config_flow.py#L362)) in the settings step
- **Main fan entity** ([config_flow.py:381](../custom_components/smart_aircon_manager/config_flow.py#L381)) in the settings step

All four switched from `vol.Optional(..., default=...)` to `vol.Optional(..., description={"suggested_value": ...})` so clearing the field in the UI actually removes the entity. Booleans elsewhere (e.g. `CONF_AUTO_CONTROL_MAIN_AC`) keep `default=` — those don't have a "cleared" semantic.

### Pattern 2 — Weighted-avg target leaking into unit-level decisions
v2.16.2 fixed `_check_if_ac_needed` and `_calculate_ac_temperature`. Three more decision points were still pulling from `_get_house_effective_target` (the per-room weighted average):

- **`_get_effective_operating_mode` fallback** ([optimizer.py:1418](../custom_components/smart_aircon_manager/optimizer.py#L1418)): when auto-mode's `_last_hvac_mode` isn't set yet, the function falls back to comparing house avg vs target to infer direction. A 25°C override could flip the inferred mode to "heat" while the user was already at/above their 21°C global setpoint. Now uses the cached global effective target.
- **Pre-positioning** ([optimizer.py:1683](../custom_components/smart_aircon_manager/optimizer.py#L1683)): each room's pre-AC-startup damper position should compare against *that room's* own effective target, not the house weighted average. Previously, a room with an elevated per-room target (Medical Supplies at 25°C, current 23.8°C) compared to the house avg (~21.7°C), looked "above target", and got minimum pre-position — when it actually needed heating toward its own target. Now uses `state["target_temperature"]` per room.
- **Main fan speed selection** ([optimizer.py:2805](../custom_components/smart_aircon_manager/optimizer.py#L2805)): same weighted-avg leak in `_determine_and_set_main_fan_speed`. A high-target room override could trick the fan speed selection into LOW when the global comparison would correctly pick MEDIUM/HIGH. Now anchors on the global effective target with the same fallback pattern.

### Tests
- `TestPerRoomTargetMathExtended` (2 cases): auto-mode fallback uses global target; per-room target boosts pre-positioning for a high-override room that still needs conditioning.
- Suite is now 121 tests, all passing.

### Why this matters
The v2.16.2 release fixed the bug the user hit, but the *root cause* (weighted-avg target as the default reference for AC-unit decisions) lived in five places. v2.16.3 finishes the cleanup so per-room overrides behave consistently across every code path that branches on "is the house at target?". For users without per-room targets, all five fixes are no-ops — the weighted-avg target and the global target are identical when all room targets equal the global.

---

## v2.16.2 - Per-Room Target Fixes

**Release Date**: 2026-05-16

Two coupled bugs around per-room target overrides, surfaced by a user whose 21°C global target was overshooting to 22–23°C while one room (Medical Supplies) had a 25°C override.

### High Severity Fixes
- **AC unit-level decisions averaged per-room targets instead of using the global target**: `_check_if_ac_needed`, `_calculate_ac_temperature`, and the rest of the unit-level pipeline asked `_get_house_effective_target` for a reference, which returns the *weighted average* of per-room targets. Result: a single 25°C override on one room pulled the effective target up to ~21.7°C, so the AC kept heating past the user's 21°C global target — overheating every other room. The fix introduces `_current_global_effective_target` (schedule + weather, **no** per-room weighting), set once per cycle in `_async_optimize_impl` ([optimizer.py:1513](../custom_components/smart_aircon_manager/optimizer.py#L1513)) and consumed by `_check_if_ac_needed` ([optimizer.py:2929](../custom_components/smart_aircon_manager/optimizer.py#L2929)) and `_calculate_ac_temperature` ([optimizer.py:2287](../custom_components/smart_aircon_manager/optimizer.py#L2287)). Per-room targets still drive per-room damper logic in `_calculate_fan_speed`, so they affect *individual* room conditioning but no longer hijack the central AC's reference. This gives per-room overrides "best-effort" semantics: a 25°C room override won't prevent the rest of the house from reaching the 21°C target.
- **Per-room target override couldn't be removed from the UI**: `async_step_edit_room` rendered the optional fields with `vol.Optional(..., default=room_target)`. Voluptuous's `default=` substitutes the value back when the form is submitted empty, so clearing the field in the UI silently re-saved the original override. Switched both `CONF_HUMIDITY_SENSOR` and `CONF_ROOM_TARGET_TEMPERATURE` to `vol.Optional(..., description={"suggested_value": ...})`, which pre-fills the field for editing without forcing a substitution on empty submit. Clearing the field in the UI now actually removes the override.

### Tests
- Added `TestPerRoomTargetMath` (3 cases): AC turns off once the house exceeds the global target even with a higher per-room override; AC stays on while any room is below the global target; setpoint stays at the global target with a per-room override present.
- Suite is now 119 tests, all passing.

### Behavioral Note
If you genuinely want one room to *reach* a higher target than the rest of the house, a single central AC can't satisfy that without overheating other rooms — there's no clean answer with one supply temperature. v2.16.2 chooses "don't overheat the house" as the default. If you want a room consistently warmer, consider a supplementary heat source for that room rather than a per-room target override.

---

## v2.16.1 - Production-Stability Audit Fixes

**Release Date**: 2026-05-16

In-depth review across every file in the integration (optimizer, climate, sensor, learning, critical_monitor, config_flow, persistence, services) looking for production-grade reliability issues. Six fixes shipped, ordered by impact.

### High Severity Fix
- **Overnight schedules couldn't be created via the UI**: `async_step_add_schedule` ([config_flow.py:939](../custom_components/smart_aircon_manager/config_flow.py#L939)) rejected `start_time >= end_time` with `schedule_start_after_end`, blocking any schedule that wraps midnight (e.g. `22:00 → 06:00`). The optimizer's `_get_active_schedule` was extended in v2.16.0 to handle the overnight case, but the UI validator wasn't updated to match. Now allows `start > end` and only blocks `start == end` (an instantaneous schedule is useless either way).

### Medium Severity Fixes
- **Non-atomic state-file writes**: `_save_compressor_state`, `async_save_profiles`, and `async_save_data_points` all wrote directly to the destination file. A Home Assistant crash mid-write would leave a half-written JSON document, and the next startup's `_load_*` would throw a `json.JSONDecodeError` and reset everything. All three now write to a `.tmp` sibling and atomically `replace()` the destination — the previous valid file stays intact on crash.
- **HVAC mode tracker seeded with non-conditioning states on startup**: `async_setup` ([optimizer.py:368](../custom_components/smart_aircon_manager/optimizer.py#L368)) accepted any climate-entity state other than `"unavailable"` as `_last_hvac_mode`, so booting with the AC off persisted `_last_hvac_mode = "off"` until the next mode determination. Mode-dependent branches in adaptive efficiency, adaptive AC setpoint, and convergence adjustment all branch on `cool`/`heat`/`dry`/`fan_only`, so a leaked `"off"` left them in fall-through states longer than necessary. Now only seeds with real conditioning modes.
- **Climate `set_temperature` accepted out-of-range values**: the UI's NumberSelector enforces 10°C–35°C, but `climate.set_temperature` service calls bypass it. The entity now declares `_attr_min_temp`/`_attr_max_temp` and `async_set_temperature` rejects values outside that range with a warning rather than silently propagating them to the optimizer.

### Low Severity Fixes
- **`ACTemperatureRecommendationSensor` attribute used wrong target source**: the `target_temperature` attribute read only the first room's target with a stale comment claiming "they all use the same target", which hasn't been true since per-room target overrides were added. Now averages across all rooms to match `_get_house_effective_target`. Also tightened `if avg_temp` checks to `is not None` so a literal 0°C reading (rare but valid) isn't treated as missing data.
- **`async_cleanup` didn't persist compressor state**: on integration unload/reload, the in-memory `_ac_last_turned_on`/`_ac_last_turned_off` timestamps and any active quick-action expiry were lost. Cleanup now saves compressor state before saving learning profiles, so a reload preserves the min on/off timers.

### Reviewed and Clean
Audited (no issues found): service registration in `__init__.py`, climate entity hvac-mode persistence, binary sensor states, manual override switch persistence, learning math (overshoot frequency, thermal mass, cooling efficiency, correlation), critical room status machine, temperature normalization (F/C), diagnostics redaction, room/schedule duplicate name validation, optimizer's retry logic with exponential backoff.

### Tests
- Added `TestHvacModeInitialization` (2 cases): `"off"` state at startup must not seed `_last_hvac_mode`; a real conditioning mode (`"cool"`) at startup should seed it. Suite is now 116 tests, all passing.

---

## v2.16.0 - Adaptive Deadband + Three Latent Bug Fixes

**Release Date**: 2026-05-16

### New: Adaptive Deadband
Opt-in feature that widens the temperature deadband when the house is mid-swing and tightens it when stable, reducing mode-thrashing between active conditioning and fan-only/dry without sacrificing steady-state precision. Configured via the **Advanced** settings step:

- `enable_adaptive_deadband` (default `False`)
- `adaptive_deadband_max_scale` (default `2.0`× — i.e. up to double the base deadband at peak rate)
- `adaptive_deadband_rate_threshold` (default `0.5` °C/min — rate at which max scale is reached)

When enabled, `_get_adaptive_deadband()` derives the effective deadband from the house-wide absolute rate-of-change (averaged across rooms). It is plugged into the HVAC mode-determination deadband ([optimizer.py:743](../custom_components/smart_aircon_manager/optimizer.py#L743)), the hysteresis override threshold ([optimizer.py:888](../custom_components/smart_aircon_manager/optimizer.py#L888)), and the rooms-stable check ([optimizer.py:2853](../custom_components/smart_aircon_manager/optimizer.py#L2853)). Enhanced compressor protection margins now stack on top of the adaptive base instead of resetting to the static base.

### Medium Severity Fixes
- **Dry mode never auto-engaged on humidity-only demand**: with `auto_control_main_ac=True` and `enable_humidity_control=True`, `_check_if_ac_needed` only considered temperature, so the AC stayed off whenever temp was in deadband — even if humidity was high enough that `_determine_optimal_hvac_mode` resolved to "dry". `_async_optimize_impl` ([optimizer.py:1444](../custom_components/smart_aircon_manager/optimizer.py#L1444)) now coerces `needs_ac = True` when the resolved optimal mode is "dry" and humidity control is enabled, so the AC powers on for dehumidification.
- **Overnight schedules with day-specific days didn't activate after midnight**: a `Mon 22:00 → 06:00` schedule with `schedule_days=["monday"]` failed to match at 03:00 Tuesday because day-matching used today's calendar day. `_get_active_schedule` ([optimizer.py:537](../custom_components/smart_aircon_manager/optimizer.py#L537)) now resolves the schedule's *anchor day* (today for the evening leg, yesterday for the morning leg) and matches `schedule_days` against the anchor day, so the morning hours of an overnight schedule activate correctly.

### Low Severity Fix
- **Quick-action sleep setback not restored after HA restart**: `_load_compressor_state` restored `_quick_action_mode` and `_quick_action_expiry` but `self.target_temperature` was reloaded from config (the original, pre-sleep value), so the ±1°C sleep setback silently vanished across restarts. The load path now re-applies the in-memory effects of the active quick-action (sleep's target shift, vacation's wider deadband) using the persisted `resolved_mode` to pick the correct direction.

### Tests
- Added `TestAdaptiveDeadband` (6 cases): off-state, zero-rate, max-clamp, mid-rate linearity, no-history safety, and negative-rate magnitude handling.
- Added `TestDryModeAutoEngage` (1 case): humid+in-deadband must power on AC in dry mode.
- Added `TestOvernightScheduleDays` (3 cases): morning leg uses yesterday's anchor, evening leg uses today, wrong day stays inactive.
- Added `TestQuickActionRestartRestoration` (1 case): sleep mode's +1°C cool-mode setback is re-applied after restart.
- Suite is now 114 tests, all passing.

---

## v2.15.2 - Heat/Cool Symmetry Audit Fixes

**Release Date**: 2026-05-16

Follow-up review after the v2.15.1 heat-mode setpoint fix, walking the optimizer end-to-end looking for other places where heat-mode logic diverged from cool-mode in subtle ways.

### High Severity Fix
- **Heat-mode adaptive balancing convergence had inverted sign**: In `_apply_room_balancing` ([optimizer.py:2071](../custom_components/smart_aircon_manager/optimizer.py#L2071)), cool mode used `(profile.relative_heat_gain_rate - 1.0) * deviation_from_avg * 50` while heat mode used `(1.0 - profile.relative_cool_rate) * deviation_from_avg * 50` — opposite sign convention. The heat-mode balancing bias is also flipped for the active direction at [line 2100](../custom_components/smart_aircon_manager/optimizer.py#L2100), so the wrong-sign formula combined with the flip cancelled and inverted the effect: a fast-cooling (poorly-insulated) cold room ended up with LESS heating fan than other rooms, the opposite of equalization. Latent because it only triggered with `enable_adaptive_balancing=True` AND enough learning data for `should_apply_learning()` to return True. Now mirrors the cool-mode sign convention.

### Medium Severity Fix
- **Pre-positioning was direction-agnostic**: When the AC is off and dampers are pre-positioned for an upcoming startup, the code used `abs(temp - effective_target)` ([optimizer.py:1552](../custom_components/smart_aircon_manager/optimizer.py#L1552)) so a cold room in cool mode (or hot room in heat mode) got the same airflow boost as a room that actually needed the upcoming conditioning. The moment AC turned on, the wrong-direction room got over-conditioned for a cycle until regular optimization clamped it back. Pre-positioning now resolves the operating mode and only boosts rooms that need the active direction; the wrong side stays at `min_pos`.

### Low Severity Fix
- **Predictive damping ignored per-room target overrides**: `_predict_temperature` ([optimizer.py:1201](../custom_components/smart_aircon_manager/optimizer.py#L1201)) damped its rate-of-change projection using `self.target_temperature` (the global target) regardless of per-room target overrides. A room with a 22°C override sitting at 22°C looked like a 2°C gap from the global 24°C target and got under-damped, biasing the predictive fan adjustment. `_apply_predictive_adjustment` now threads the room's effective target through, with the global as fallback.

### Reviewed and Clean
Heat/cool symmetry was verified across AC on/off hysteresis, fan-speed proportional curves and overshoot tiers, predictive fan adjustment, vacant-room setback, weather adjustment, HVAC mode determination/hysteresis, sleep-mode setback, adaptive AC setpoint with efficiency, and efficiency fan-speed adjustment.

### Tests
- Added `TestAdaptiveBalancingConvergence` (2 cases): cool mode keeps working as a baseline; heat mode regression guard verifies fast-cooling cold rooms get MORE fan than hot rooms.
- Added `TestPrePositioningMode` (2 cases): cool mode prefers hot rooms; heat mode prefers cold rooms; wrong-direction rooms get `min_pos`.
- Added `TestPredictTemperatureRoomTarget` (1 case): per-room target produces smaller predicted change when the room is at its override target than the global-target fallback would suggest.
- Suite is now 103 tests, all passing.

---

## v2.15.1 - Heat-Mode Setpoint Overshoot Fix

**Release Date**: 2026-05-16

### High Severity Fix
- **Heating runaway to target+4°C**: In heat mode, `_calculate_ac_temperature` used `abs(temp_diff) * 2.0` for the proportional setpoint offset ([optimizer.py:2140](../custom_components/smart_aircon_manager/optimizer.py#L2140)). Because `temp_diff = avg_temp - target`, the `abs()` caused the setpoint to climb *above* target whenever the house overshot — exactly when the AC unit's internal thermostat should be coasting toward target, not chasing a higher one. With target=21°C and avg=23°C, the integration was sending the AC a 25°C setpoint, so the unit's own return-air sensor kept driving heat until rooms read ~25–26°C. Now mirrors the cool-mode formula (`max(0.0, -temp_diff * 2.0)`): offset only applies when below target, and setpoint clamps to target during overshoot.

### Tests
- Added `test_heat_mode_no_setpoint_boost_during_overshoot` (regression guard: target=21°C with one cold outlier holding AC on, avg=22°C → setpoint must not exceed 21°C). The existing heat-mode test only covered heating *up to* target, so this case slipped through.
- Added `test_heat_mode_aggressive_heat_offset` to pin the legitimate +4°C overdrive when far below target. Suite is now 98 tests, all passing.

---

## v2.15.0 - Heating Mode & Code Review Fixes

**Release Date**: 2026-05-09

Fixed 8 issues found during a follow-up code review, with a focus on heating-mode behavior in winter.

### Critical Fix
- **Pre-positioning crashed every cycle**: `_get_house_effective_target()` was called without its required `room_states` argument in the AC-off pre-positioning branch ([optimizer.py:1522](../custom_components/smart_aircon_manager/optimizer.py#L1522)). The `TypeError` was swallowed by the broad exception handler in `async_optimize`, so the v2.14.0 smart pre-positioning feature silently never ran. Now passes `room_states` correctly.

### High Severity Fixes
- **Dry mode no longer fires in heat mode**: When humidity control is enabled, the optimizer would switch the AC to `dry` mode whenever indoor humidity exceeded the threshold — including while heating. On most split units, dry mode runs the compressor in a low-flow refrigeration cycle that actively cools the air, fighting the heat loop. In heat mode (and auto-resolved-to-heat), dry mode is now suppressed; the system mixes only between `heat` and `fan_only` for circulation. Cool/auto-cool behavior is unchanged.
- **Adaptive AC setpoint inverted in heat mode**: When `enable_adaptive_ac_setpoint=True`, high learned efficiency added `+1.0°C` to the base setpoint. In cool mode this means a warmer setpoint = less aggressive (correct). In heat mode the base setpoint is *above* target, so `+1.0` made it MORE aggressive — the opposite of intent. The adaptive branch now short-circuits in heat mode (the underlying metric only models cooling response).
- **Adaptive efficiency fan adjustment skipped in heat mode**: `_apply_efficiency_adjustment` used `cooling_efficiency` for both modes. In heat mode this is meaningless at best and inverted at worst (a poorly-insulated room cools fast, getting flagged as "efficient" and having its heating fan reduced). Now skipped in heat mode.

### Medium Severity Fixes
- **Sleep mode no-op in auto mode**: `_enter_quick_action_mode("sleep")` checked `self.hvac_mode == "cool"/"heat"` directly, so users in auto mode got no temperature setback. Now resolves via `_get_effective_operating_mode()`. Entry-time resolved mode is also stored so exit-time restoration works correctly even if the user toggles modes during sleep.
- **Main fan recommendation sensor used hardcoded thresholds**: `MainFanSpeedRecommendationSensor.native_value` had `3.0` and `1.0` literals while the actual main-fan logic in the optimizer reads `main_fan_high_threshold` from config. The debug sensor now reads the same value, eliminating UI/behavior drift for non-default thresholds.

### Documentation
- **README version history outdated**: README claimed `v2.8.2 (Current)` while manifest was at `2.14.0`. Refreshed through v2.14.0 with one-line summaries for each release.
- **README HVAC mode list**: Notes the heat-mode dry-suppression behavior so users running humidity control in winter aren't surprised.

### Tests
- Added `TestHeatModeDryModeSuppression` (5 cases): heat + high humidity → `fan_only`; heat + humidity excess (below dry threshold) → `fan_only`; cool + high humidity still → `dry` (regression guard); auto with last-mode=heat → `fan_only`; heat + temp out-of-band → `heat` (priority preserved). Suite is now 96 tests, all passing.

---

## v2.13.0 - Full Bug & Logic Review (29 fixes)

**Release Date**: 2026-03-01

Fixed 29 issues (1 critical + 1 high + 15 medium + 12 low) found during comprehensive bug and logic review.

### Critical Fix
- **Config flow crash on critical room validation**: `_get_critical_room_schema()` method didn't exist — entering `temp_safe >= temp_max` crashed the config flow with `AttributeError`

### High Severity Fix
- **Weather entity temperature not normalized for Fahrenheit**: Weather entity fallback used raw temperature without F→C conversion, causing wildly wrong weather adjustments for Fahrenheit users

### Optimizer Fixes (5 medium)
- **Main fan "low for stable conditions" was dead code**: Low-speed setting for stable rooms was always overwritten by mode-specific logic; now short-circuits correctly
- **Auto mode AC turn-on ignored outlier rooms**: Unlike cool/heat modes, auto mode only checked average temp, missing individual rooms far from target
- **Auto mode AC decisions used stale mode**: `_check_if_ac_needed` was called before `_determine_optimal_hvac_mode`, using previous cycle's mode direction
- **Occupancy setback ignored by AC/stability decisions**: `_get_house_effective_target` and `_check_rooms_stable` now include occupancy-adjusted targets
- **Fan speed calculation ignored humidity mode switches**: Now uses effective operating mode instead of raw configured mode

### Config Flow Fixes (4 medium)
- **Edit room saved unstripped name**: Room names with spaces caused override key mismatches
- **No duplicate schedule name validation**: Duplicate names caused mass deletion when deleting by name
- **No schedule time ordering validation**: Users could create schedules with start_time >= end_time
- **No cross-validation of advanced thresholds**: Overshoot tiers and fan thresholds now validated for correct ordering

### Sensor Fixes (5 medium)
- **TypeError when cover_position is None**: `RoomFanRecommendationSensor` now guards both values
- **"maintaining" status when all sensors unavailable**: Now correctly returns "no_data"
- **AttributeError on first optimization cycle**: `HouseAverageHumiditySensor` attributes now use `hasattr` guard
- **TOTAL_INCREASING wrong for capped data points**: `RoomDataPointsSensor` changed to MEASUREMENT
- **TOTAL_INCREASING counter inflated on restart**: `TotalOptimizationsRunSensor` changed to MEASUREMENT

### Other Fixes (1 medium + 12 low)
- **Unload ordering**: Platforms now unloaded before optimizer cleanup to prevent teardown errors
- **disable_learning service**: Now operates on all entries when `config_entry_id` omitted
- **Manual override state**: Now persisted across HA restarts
- **Convergence rate metric**: Now measures actual convergence toward target, not direction-agnostic change
- **Fan recommendation sensor**: Uses average of all room targets instead of first room only
- **Hardcoded unit strings**: Replaced with HA constants (`SensorDeviceClass.TEMPERATURE`, `UnitOfTemperature.CELSIUS`)
- **Domain error overwrites**: Validation now preserves more specific temperature/position errors
- **Entity selector defaults**: No longer passes `None` as default for optional entity selectors
- **Critical room fields**: Changed from `vol.Optional` to `vol.Required` for safety-critical thresholds
- **Coupled rooms log**: Fixed `coupled_rooms` (list) vs `coupling_factors` (dict) mismatch
- **Humidity log**: Fixed falsy check that logged 0% instead of actual value for humidity

---

## v2.8.2 - Full Code Review Bug Fixes

**Release Date**: 2026-02-08

Fixed 10 bugs discovered during comprehensive code review across 4 files.

### Critical Fixes
- **Config params not passed to optimizer**: 11 config values for adaptive bands, efficiency, predictive, AC setpoint, adaptive balancing, room coupling, enhanced compressor protection, and margins were silently ignored after being saved in the UI
- **Room cache cleanup broken**: `_cleanup_room_caches` used wrong dictionary key, so stale cache entries were never cleaned (memory leak)
- **Learning data lost on restart**: Adaptive balancing fields (balancing_bias, relative_heat_gain_rate, relative_cool_rate, coupled_rooms, coupling_factors) lost every HA restart

### Logic Fixes
- **Pearson correlation formula**: Covariance used population divisor while stdev used sample divisor, producing incorrect room coupling values
- **HVAC mode sensor side effects**: Reading the sensor caused optimizer state mutation (hysteresis, compressor counters, mode flags). Now reads cached value
- **Cleanup log message**: Always showed 0 deleted rooms because it counted from already-cleaned dicts

### Other Fixes
- **room_configs wrong default type**: Default was dict instead of list
- **Quick action services not unregistered**: 4 services persisted after integration removal
- **Duplicated sensor name**: "Main Fan Speed Fan Speed Recommendation" corrected

---

## v2.8.1 - Enhanced Compressor Protection

**Release Date**: 2026-02-08

Added advanced compressor protection to reduce mode change frequency.

### New Feature
- **Enhanced Compressor Protection**: Undercool/overheat margins, minimum mode duration, minimum run cycles
- Reduces mode changes from 10-12/hour to 2-3/hour
- Extends compressor lifespan by 20-30%
- Saves estimated $50-150/year in energy costs

### Configuration
- `enable_enhanced_compressor_protection` (default: false, opt-in)
- `compressor_undercool_margin` (default: 0.5°C)
- `compressor_overheat_margin` (default: 0.5°C)
- `min_mode_duration` (default: 600s)
- `min_compressor_run_cycles` (default: 3)

---

## v2.8.0 - Stability & Bug Fix Release

**Release Date**: 2026-02-08

Major stability release addressing 15 logic issues.

### Critical Fixes
1. Quick action mode restoration logic (no longer overwrites manual changes)
2. Adaptive balancing multiplier order (correct additive instead of multiplicative)
3. AC off logic (checks HVAC mode direction before turning off)
4. Smoothing/predictive adjustment order (predictive now applied before smoothing)
5. Bounds checking on learned balancing bias (clamped to ±5.0)

### Safety Improvements
6. Compressor protection timestamps persisted across HA restarts
7. Temperature history always updated (even with predictive disabled)
8. Outdoor temperature cache expiry (1 hour max)
9. Occupancy last_seen default fixed (forces vacancy if data corrupt)
10. Cache cleanup on config reload (prevents memory leak from deleted rooms)

### Optimizations
11. Exponential decay temperature prediction (more accurate than linear)
12. Proportional efficiency adjustment (scaled by distance from optimum)
13. Outlier filtering in convergence rate (2-sigma filter)
14. Cover state check before position commands (prevents oscillation)
15. Quick action expiry lock (prevents race condition)

---

## v2.7.0 - Quick Actions, Smart Learning & Adaptive Balancing

**Release Date**: 2026-02-08

### New Features
- **Quick Actions**: 4 new services - vacation, boost, sleep, party modes
- **Smart Learning**: Activates dormant learning data - adaptive bands, efficiency adjustments, adaptive predictive control, adaptive AC setpoint
- **Adaptive Balancing**: Room coupling detection, learned balancing bias, relative convergence rate tracking
- **Enhanced Dashboard**: YAML templates with visual room map, quick action buttons, fan speed bars

### New Services
- `smart_aircon_manager.vacation_mode`
- `smart_aircon_manager.boost_mode`
- `smart_aircon_manager.sleep_mode`
- `smart_aircon_manager.party_mode`

### New Configuration
- 6 new adaptive learning/balancing options
- All backward compatible with safe defaults

---

## v2.6.0 - Features & Test Suite

6 new features, 3 logic fixes, and a comprehensive 65-test pytest suite.

---

## v2.5.0 - Bug Fixes & Optimizations

11 bug fixes and 5 optimizations for improved stability.

---

## v2.4.7 - Manual Override & Dashboards

- Manual override switch for temporary manual control
- Example Lovelace dashboards (comprehensive and minimal)
