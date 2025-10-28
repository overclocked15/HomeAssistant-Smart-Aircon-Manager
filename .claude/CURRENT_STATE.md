# Current Technical State - v1.5.0

## Quick Reference

### Version Information
- **Current Version:** 1.5.0
- **Last Release:** 2025-10-25
- **Git Branch:** main
- **Last Commit Hash:** 71a037b

### Active Features

#### 1. Data Polling (v1.3.8)
- **Polling Interval:** 30 seconds (hardcoded in const.py)
- **AI Optimization Interval:** 5 minutes (configurable via options)
- **Implementation:** DataUpdateCoordinator in __init__.py (line 80)

#### 2. Main Fan Speed Control (v1.4.0)
- **Cool Mode Logic:** High if temps above target, Low if below
- **Heat Mode Logic:** High if temps below target, Low if above
- **Implementation:** optimizer.py `_determine_and_set_main_fan_speed()` (lines 566-713)

#### 3. Room Fan Speed Control (v1.4.1)
- **AI Prompt:** Directionally-aware, shows temp difference with sign
- **Cool Mode:** High fan for rooms above target, Low for rooms below
- **Heat Mode:** High fan for rooms below target, Low for rooms above
- **Implementation:** optimizer.py `_build_optimization_prompt()` (lines 370-469)

#### 4. AC Auto On/Off with Hysteresis (v1.5.0)
- **Turn ON Threshold:** 1.0°C (DEFAULT_AC_TURN_ON_THRESHOLD)
- **Turn OFF Threshold:** 2.0°C (DEFAULT_AC_TURN_OFF_THRESHOLD)
- **Cool Mode:**
  - Turn ON: avg_temp ≥ target + 1.0°C
  - Turn OFF: avg_temp ≤ target - 2.0°C AND max_temp ≤ target
- **Heat Mode:**
  - Turn ON: avg_temp ≤ target - 1.0°C
  - Turn OFF: avg_temp ≥ target + 2.0°C AND min_temp ≥ target
- **Implementation:** optimizer.py `_check_if_ac_needed()` (lines 715-813)

### Configuration Constants (const.py)

```python
# Polling and Timing
DEFAULT_UPDATE_INTERVAL = 5  # minutes - AI optimization interval
DEFAULT_DATA_POLL_INTERVAL = 30  # seconds - sensor data polling
DEFAULT_STARTUP_DELAY = 120  # seconds - boot notification delay

# Temperature Control
DEFAULT_TARGET_TEMPERATURE = 22  # °C
DEFAULT_TEMPERATURE_DEADBAND = 0.5  # °C - comfort zone around target

# AC Auto Control Hysteresis
DEFAULT_AC_TURN_ON_THRESHOLD = 1.0  # °C above target to turn AC on
DEFAULT_AC_TURN_OFF_THRESHOLD = 2.0  # °C below target to turn AC off

# Modes
DEFAULT_HVAC_MODE = HVAC_MODE_COOL  # "cool"
DEFAULT_AUTO_CONTROL_MAIN_AC = False
DEFAULT_ENABLE_NOTIFICATIONS = True

# AI Models
DEFAULT_CLAUDE_MODEL = "claude-3-5-sonnet-20241022"
DEFAULT_CHATGPT_MODEL = "gpt-4-turbo-preview"
```

### Key Functions

#### optimizer.py
- `async_optimize()` - Main optimization loop (lines 70-230)
- `_collect_room_states()` - Gather temperature and fan data (lines 232-326)
- `_get_ai_recommendations()` - Call AI API for fan speeds (lines 328-368)
- `_build_optimization_prompt()` - Build AI prompt (lines 370-469)
- `_apply_recommendations()` - Set room fan speeds (lines 471-530)
- `_determine_and_set_main_fan_speed()` - Set main fan (lines 566-713)
- `_check_if_ac_needed()` - Hysteresis logic (lines 715-813)
- `_control_main_ac()` - Turn AC on/off (lines 815-856)

#### sensor.py
Key sensors:
- `RoomTemperatureDifferenceSensor` - Shows temp vs target per room
- `RoomAIRecommendationSensor` - Shows AI recommended fan speed per room
- `RoomFanSpeedSensor` - Shows current fan speed per room
- `AIOptimizationStatusSensor` - Overall system status
- `MainFanSpeedSensor` - Main AC fan speed
- `MainFanSpeedRecommendationSensor` - Debug sensor with mode-aware logic (lines 412-500)
- `SystemStatusDebugSensor` - Debug information
- `LastOptimizationTimeSensor` - Last AI run timestamp
- `ErrorTrackingSensor` - Error count and status
- `ValidSensorsCountSensor` - Count of working sensors

### Data Flow

1. **Every 30 seconds (Data Poll):**
   ```
   Coordinator triggers → async_optimize()
   → _collect_room_states() → Returns room temps and fan positions
   → Check if AI optimization needed (time-based)
   → If not time yet: Return cached AI recommendations
   → If time: Call _get_ai_recommendations() → Apply changes
   → Update coordinator.data with room_states, recommendations, main_fan_speed
   → All sensors read from coordinator.data
   ```

2. **Every 5 minutes (AI Optimization):**
   ```
   async_optimize() detects it's time for AI
   → _get_ai_recommendations() builds prompt and calls Claude/ChatGPT
   → AI returns JSON with room fan speeds
   → _apply_recommendations() sets each room's fan speed
   → _determine_and_set_main_fan_speed() calculates and sets main fan
   → Cache results in _last_recommendations and _last_main_fan_speed
   ```

3. **AC Auto Control (if enabled):**
   ```
   async_optimize() → _check_if_ac_needed(room_states, ac_currently_on)
   → Hysteresis logic determines if AC should be on or off
   → _control_main_ac(needs_ac, main_climate_state)
   → Turns AC on/off via climate.set_hvac_mode service
   → Sends notification to user
   ```

### Coordinator Data Structure

```python
coordinator.data = {
    "room_states": {
        "Room Name": {
            "current_temperature": 21.5,
            "target_temperature": 22.0,
            "cover_position": 75,
            "temperature_sensor": "sensor.room_temp",
            "cover_entity": "cover.room_fan"
        },
        # ... more rooms
    },
    "recommendations": {
        "Room Name": 50,  # AI recommended fan speed 0-100
        # ... more rooms
    },
    "ai_response_text": "Full AI response text",
    "main_climate_state": {
        "state": "cool",
        "temperature": 22.0,
        "current_temperature": 23.5,
        "hvac_mode": "cool",
        "hvac_action": "cooling"
    },
    "main_fan_speed": "medium",  # "low", "medium", or "high"
    "main_ac_running": True,
    "needs_ac": True,
    "last_error": None,
    "error_count": 0
}
```

### Logging Levels

```python
# optimizer.py logs at INFO level:
- "Running AI optimization (first run: True, 0.0s since last)"
- "Data collection only (next AI optimization in 240.0s, using cached: recs=True, fan=medium)"
- "Main fan -> LOW: Temps below target in cool mode (avg: -1.0°C)"
- "AC turn ON check: avg=23.2°C (+1.2°C above target), threshold=1.0°C → Turn ON"
- "Optimization cycle complete: rooms=2, recommendations=2, main_fan=low, ac_running=False"

# Use DEBUG level for more detail in configuration.yaml:
logger:
  default: info
  logs:
    custom_components.ai_aircon_manager: debug
```

### Common Issues and Solutions

1. **Entities showing "unknown":**
   - Check if coordinator.data is being populated
   - Look for errors in logs during async_optimize()
   - Verify sensors have valid temperature readings

2. **AI not running:**
   - Check if AC is running (only optimizes when AC on, unless no main_climate_entity)
   - Verify API key is valid
   - Check for AI API errors in logs

3. **Main fan speed wrong:**
   - Verify hvac_mode is correctly set (cool/heat)
   - Check temperature sensors are reading correctly
   - Look at "Main fan -> " log messages for reasoning

4. **AC cycling too much:**
   - Verify hysteresis thresholds (1.0°C on, 2.0°C off by default)
   - Check if auto_control_main_ac is enabled
   - Look at "AC turn ON/OFF check" log messages

### Development Workflow

1. Make changes to code
2. Update version in manifest.json and __init__.py
3. Commit with detailed message
4. Push to GitHub
5. Create GitHub release with comprehensive notes
6. User updates via HACS
7. User tests and provides feedback

### Testing Commands

```bash
# Check integration status in Home Assistant
# Look for these sensors in Developer Tools > States:
sensor.ai_optimization_status
sensor.main_aircon_fan_speed
sensor.main_fan_speed_ai_recommendation
binary_sensor.main_aircon_running
sensor.system_status_debug

# Check logs
tail -f /config/home-assistant.log | grep ai_aircon_manager

# Force reload integration
# Settings > Devices & Services > AI Aircon Manager > ... > Reload
```

---

Last Updated: 2025-10-25
Version: 1.5.0
