# Troubleshooting Guide

## Common Issues

### Integration Not Appearing

**Symptom**: Can't find "Smart Aircon Manager" when adding integrations.

**Solutions**:
1. Verify files are in `config/custom_components/smart_aircon_manager/`
2. Check that `manifest.json` exists in that directory
3. Restart Home Assistant completely (not just reload)
4. Check HA logs for import errors: **Settings** > **System** > **Logs**

### System Not Making Adjustments

**Symptom**: Fans aren't moving, temperatures aren't being controlled.

**Check**:
1. Is manual override off? Check `switch.smart_aircon_manager_manual_override`
2. Is the climate entity in `auto` mode? Check `climate.smart_aircon_manager`
3. Are temperature sensors working? Check `sensor.smart_aircon_manager_valid_sensors_count`
4. Is there an error? Check `sensor.smart_aircon_manager_error_tracking`
5. When was the last optimization? Check `sensor.smart_aircon_manager_last_optimization`

### Rooms Not Reaching Target

**Symptom**: Temperature stays too hot or too cold.

**Check**:
1. Is your main AC set to an appropriate temperature? The zone dampers only control airflow distribution; the AC provides the cooling/heating
2. Verify zone fan entities are actually changing speed (test manually)
3. Check if a room override is disabling the room
4. Look at `sensor.smart_aircon_manager_{room}_recommendation` to see what the system wants to do
5. Enable debug logging to see the decision-making process

### Fan Speeds Seem Stuck

**Symptom**: Fan speeds don't change between cycles.

**Causes**:
- **Smoothing**: Small changes are smoothed out. Try `smart_aircon_manager.reset_smoothing`
- **Stability detection**: If temperatures are stable, the system reduces the frequency of changes
- **Cover in motion**: The system waits for covers to finish moving before issuing new commands

### Quick Action Mode Won't Activate

**Symptom**: Calling vacation/boost/sleep/party service has no effect.

**Check**:
1. Is manual override on? Quick actions are blocked during manual override
2. Is `config_entry_id` correct? Check Developer Tools > States for the correct ID
3. Check HA logs for error messages
4. Verify the service exists: Developer Tools > Services > search for `smart_aircon_manager`

### Learning Not Working

**Symptom**: Learning confidence stays at 0, no adaptive adjustments being made.

**Check**:
1. Is learning enabled? Call `smart_aircon_manager.enable_learning` with `mode: "active"`
2. Check data points: `sensor.smart_aircon_manager_{room}_data_points` should be >200
3. Check confidence: `sensor.smart_aircon_manager_{room}_learning_confidence` needs to be >= 0.7
4. Learning requires consistent operation (not constantly in manual override)
5. Adaptive features need to be enabled in config (most are enabled by default)

### AC Cycling Too Frequently

**Symptom**: AC turns on and off every few minutes.

**Solutions**:
1. Enable enhanced compressor protection:
   ```yaml
   enable_enhanced_compressor_protection: true
   compressor_undercool_margin: 0.5
   min_mode_duration: 600
   ```
2. Increase `ac_turn_on_threshold` and `ac_turn_off_threshold`
3. Increase `mode_change_hysteresis_time`
4. Check that basic compressor protection is enabled (it is by default)

### Temperature Oscillation

**Symptom**: Room temperature swings up and down around the target.

**Solutions**:
1. Increase `temperature_deadband` (default 0.5°C)
2. Enable fan smoothing (enabled by default)
3. Reduce `balancing_aggressiveness` if balancing is causing oscillation
4. Enable predictive control to anticipate changes
5. If learning is active, it will automatically adjust smoothing over time

### Sensors Show "Unknown" or "Unavailable"

**Symptom**: Smart Aircon Manager sensors show unknown/unavailable states.

**Check**:
1. Are the underlying temperature sensors working?
2. Has the integration loaded successfully? Check HA logs
3. Try reloading: **Settings** > **Devices & Services** > **Smart Aircon Manager** > **Reload**
4. If sensors disappeared after an update, restart HA

### High Error Count

**Symptom**: `sensor.smart_aircon_manager_error_tracking` shows many errors.

**Common causes**:
- Temperature sensors intermittently unavailable (check WiFi, battery)
- Cover entities not responding (check Z-Wave/Zigbee mesh)
- Main climate entity offline

**Solutions**:
1. Check HA logs for specific error messages
2. Verify all configured entities exist and are available
3. Reset error count after fixing: `smart_aircon_manager.reset_error_count`

## Debug Logging

Enable detailed logging to diagnose issues:

```yaml
logger:
  default: info
  logs:
    custom_components.smart_aircon_manager: debug
```

This shows:
- Optimization cycle timing and decisions
- Fan speed calculations for each room
- AC control decisions (on/off, temperature, mode)
- Room balancing adjustments
- Predictive control calculations
- Learning data collection and analysis
- Compressor protection decisions
- Quick action mode changes
- Error details

### Reading Debug Logs

Key log patterns to look for:

```
# Optimization cycle
"Starting optimization cycle"
"Optimization cycle completed in X ms"

# Fan speed decisions
"Room X: temp=24.5°C, target=22.0°C, deviation=2.5°C, fan_speed=75%"

# AC control
"AC needs to turn ON: avg_temp=24.0°C exceeds threshold"
"Compressor protection: blocking turn-on (off for only 60s, need 180s)"

# Mode changes
"HVAC mode change: cool → fan_only"
"Mode change hysteresis active: keeping cool mode"

# Learning
"Room X: confidence=0.85, thermal_mass=0.65, efficiency=0.72"
"Using learned adaptive bands for Room X"
```

## Performance Monitoring

Track system health using these sensors:

| Sensor | Healthy Value | Concern |
|--------|--------------|---------|
| `optimization_cycle_time` | <100ms | >1000ms |
| `error_tracking` | 0 | >10 |
| `valid_sensors_count` | = number of rooms | < number of rooms |

## Getting Help

If you're still stuck:

1. Enable debug logging and capture relevant log entries
2. Note your configuration (target temp, number of rooms, enabled features)
3. Check [existing issues](https://github.com/overclocked15/HomeAssistant-Smart-Aircon-Manager/issues)
4. Open a [new issue](https://github.com/overclocked15/HomeAssistant-Smart-Aircon-Manager/issues/new) with:
   - HA version and Smart Aircon Manager version
   - Your configuration (without sensitive data)
   - Relevant debug log entries
   - Steps to reproduce the issue
