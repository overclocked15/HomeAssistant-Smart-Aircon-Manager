# Smart Aircon Manager

A Home Assistant integration that uses **intelligent logic-based algorithms** to automatically manage your air conditioning system by adjusting zone fan speeds based on temperature sensors in each room. **No AI API required** - completely free and runs 100% locally!

> **This is the free, logic-based alternative** to the AI-powered version. It uses smart algorithms and rules to achieve similar results without requiring expensive AI API subscriptions.

## Features

### Core Capabilities
- **Logic-Based Management**: Smart algorithms intelligently manage zone fan speeds
- **100% Local**: No external API calls, completely private and free
- **Multi-Room Support**: Configure multiple rooms with individual temperature sensors and zone controls
- **Temperature Equalization**: Automatically balances temperatures across all rooms
- **Smart Redistribution**: Increases fan speed in hot rooms, reduces in cold rooms to equalize
- **Main Aircon Fan Control**: Automatically adjusts your main AC unit's fan speed (low/medium/high) based on system needs
- **Automatic AC On/Off Control**: Can automatically turn your main AC on/off based on need with hysteresis
- **Automatic AC Temperature Control**: Can automatically control your main AC's temperature setpoint for fully hands-off operation
- **Comprehensive Diagnostics**: Detailed sensors for monitoring and troubleshooting
- **Climate Entity**: Provides a climate entity to view overall system status and set target temperature
- **Flexible Configuration**: Easy UI-based setup through Home Assistant config flow with options to reconfigure

### Advanced Features
- **Room Overrides**: Disable control for specific rooms while keeping others active
- **Heating/Cooling Modes**: Support for both heating and cooling with mode-aware optimizations
- **HVAC Mode Auto-Detection**: Can automatically detect heating/cooling from main climate entity
- **Hysteresis Control**: Prevents rapid AC on/off cycling with configurable thresholds
- **HVAC Mode Change Hysteresis** *(NEW in v2.3.0)*: Prevents rapid mode switching (cool/heat/dry/fan_only) unless temperature deviation is severe, reducing wear on equipment
- **Startup Delay**: Grace period during Home Assistant startup to prevent false alarms
- **Persistent Notifications**: Optional notifications for important events (AC control, errors)
- **Comfort Index Sensor** *(NEW in v2.3.0)*: Shows "feels-like" temperature combining temperature and humidity using heat index calculation
- **Occupancy-Based Control** *(NEW in v2.3.0)*: Automatically applies temperature setbacks to vacant rooms for energy savings
  - Configurable occupancy sensors per room
  - Vacancy timeout prevents premature setback
  - Setback amount: ±2°C from target (increases in cooling, decreases in heating)

### Smart Automation Features
- **Weather Integration**: Automatically adjusts target temperature based on outdoor conditions
  - Hot weather (>30°C): Sets AC slightly cooler to combat heat
  - Cold weather (<15°C): Sets AC slightly warmer to prevent overcooling
  - Supports weather entities and outdoor temperature sensors
- **Time-Based Scheduling**: Different target temperatures for different times and days
  - Multiple schedules with individual target temperatures
  - Day-of-week scheduling (weekdays, weekends, specific days, or all days)
  - Time range support including cross-midnight schedules (e.g., 22:00-08:00)
  - Schedule priority over base target temperature
- **Progressive Overshoot Handling**: Gradual fan reduction for rooms that overshoot target while maintaining air circulation
  - Small overshoot (<1°C): Reduced to 25-35% for gentle correction
  - Medium overshoot (1-2°C): Reduced to 15-25% for moderate correction
  - High overshoot (2-3°C): Reduced to 5-15% for minimal airflow
  - Severe overshoot (3°C+): Shutdown to 0-5% only in extreme cases
- **Improved Main Fan Logic**: Smarter thresholds for low/medium/high fan speeds

## How It Works

1. The integration monitors temperature sensors in each configured room
2. **Fast polling**: Reads sensor data every **10 seconds** for responsive monitoring
3. **Frequent optimization**: Adjusts fan speeds every **30 seconds** for precise control
4. **Granular logic-based algorithm** calculates optimal fan speeds with 8 temperature bands:
   - **4°C+ above target**: 100% fan speed (extreme heat/cold)
   - **3-4°C above**: 90% fan speed (very hot/cold)
   - **2-3°C above**: 75% fan speed (hot/cold)
   - **1.5-2°C above**: 65% fan speed (moderately hot/cold)
   - **1-1.5°C above**: 55% fan speed (slightly hot/cold)
   - **0.7-1°C above**: 45% fan speed (just above target)
   - **0.5-0.7°C above**: 40% fan speed (barely above target)
   - **Within 0.5°C**: 50% fan speed (at target - maintain circulation)
5. **Progressive overshoot handling** for rooms that are too cold/warm
6. **Optional**: Can also set optimal AC temperature setpoint based on room conditions
7. This creates smooth, responsive temperature equilibrium across your entire house
8. The fast update cycle (30s) ensures rooms quickly reach and maintain target temperature

### Why Logic-Based Instead of AI?

The logic-based approach offers several advantages:

- **Zero Cost**: No monthly API fees (AI version costs $1-4/month)
- **100% Private**: No data sent to external services
- **Predictable**: Deterministic behavior you can understand and trust
- **Fast**: Instant decisions without API latency
- **Reliable**: No dependency on external services
- **Transparent**: You can see exactly how decisions are made

The logic algorithms are based on proven HVAC control strategies and have been carefully tuned to provide excellent temperature management.

## Prerequisites

- Home Assistant with custom integrations support
- Temperature sensors for each room (e.g., `sensor.bedroom_temperature`)
- Cover entities representing zone fan speed controls (e.g., `cover.bedroom_zone_fan`)

## Installation

### Option 1: HACS (Recommended)

1. Open HACS in Home Assistant
2. Click on "Integrations"
3. Click the three dots in the top right corner and select "Custom repositories"
4. Add this repository URL: `https://github.com/overclocked15/HomeAssistant-Smart-Aircon-Manager`
5. Select category "Integration"
6. Click "Add"
7. Find "Smart Aircon Manager" in the list and click "Download"
8. Restart Home Assistant

### Option 2: Manual Installation

1. Download this repository
2. Copy the `custom_components/smart_aircon_manager` folder to your Home Assistant `config/custom_components/` directory
3. Your directory structure should look like:
   ```
   config/
   └── custom_components/
       └── smart_aircon_manager/
           ├── __init__.py
           ├── climate.py
           ├── config_flow.py
           ├── const.py
           ├── manifest.json
           ├── optimizer.py
           ├── sensor.py
           ├── binary_sensor.py
           └── translations/
               └── en.json
   ```
4. Restart Home Assistant

## Configuration

### Initial Setup

1. Go to **Settings** → **Devices & Services**
2. Click **Add Integration**
3. Search for "Smart Aircon Manager"
4. Follow the configuration steps:
   - **Step 1**:
     - Set target temperature (e.g., 22°C)
     - **(Optional)** Main Aircon Climate Entity - for monitoring and auto on/off control
     - **(Optional)** Main AC Fan Control - can be the same climate entity OR a separate fan entity
       - If your climate entity has fan modes (low/medium/high), use that
       - System will automatically detect and use `climate.set_fan_mode` or `fan.set_preset_mode`
   - **Step 2**: Add rooms one by one:
     - Room name (e.g., "Bedroom")
     - Temperature sensor entity
     - Zone fan speed control entity
   - Keep adding rooms until all configured

### Reconfiguring Settings

You can change settings after initial setup:

1. Go to **Settings** → **Devices & Services**
2. Find "Smart Aircon Manager" and click **Configure**
3. Choose what you want to configure:
   - **Change Settings**: Update target temperature, HVAC mode, main climate entity, etc.
   - **Manage Rooms**: Add or remove rooms
   - **Room Overrides**: Enable/disable control for specific rooms
   - **Weather**: Configure weather integration and outdoor temperature adjustments
   - **Schedules**: Manage time-based temperature schedules

#### Key Settings

**In "Change Settings":**
- **Target Temperature**: Your desired comfort temperature
- **Temperature Deadband**: Acceptable range (±) from target before taking action (default: 0.5°C)
- **Update Interval**: How often optimization runs (default: 30 seconds)
- **HVAC Mode**: Cooling, Heating, or Auto (detect from main climate)
- **Automatically turn main AC on/off**: Enable automatic AC control with hysteresis
- **Automatically control AC temperature**: Enable full automation of AC temperature setpoint
- **Enable notifications**: Get notified of important events

## Logic-Based Algorithm Details

### Performance Characteristics
- **Polling Frequency**: Every 10 seconds (sensor monitoring)
- **Optimization Frequency**: Every 30 seconds (fan speed adjustments)
- **Response Time**: Typically reaches target temperature in 5-15 minutes
- **Stability**: Maintains ±0.5°C of target once achieved
- **Granularity**: 8 temperature bands for smooth, precise control

### Cooling Mode Strategy

**For rooms ABOVE target** (need cooling) - 8 granular bands:
- **4°C+ above**: 100% fan (extreme heat - maximum cooling)
- **3-4°C above**: 90% fan (very hot - aggressive cooling)
- **2-3°C above**: 75% fan (hot - strong cooling)
- **1.5-2°C above**: 65% fan (moderately hot - good cooling)
- **1-1.5°C above**: 55% fan (slightly hot - moderate cooling)
- **0.7-1°C above**: 45% fan (just above - gentle cooling)
- **0.5-0.7°C above**: 40% fan (barely above - minimal cooling)

**For rooms BELOW target** (overshot, too cold) - 5 progressive bands:
- **3°C+ below**: 5% fan (severe overshoot - near shutdown)
- **2-3°C below**: 12% fan (high overshoot - minimal airflow)
- **1-2°C below**: 22% fan (medium overshoot - reduced cooling)
- **0.7-1°C below**: 30% fan (small overshoot - gentle reduction)
- **0.5-0.7°C below**: 35% fan (very small overshoot - slight reduction)

**For rooms AT TARGET** (within ±0.5°C deadband):
- **50% fan** (baseline circulation - maintains comfort)

### Heating Mode Strategy

**For rooms BELOW target** (need heating) - 8 granular bands:
- **4°C+ below**: 100% fan (extreme cold - maximum heating)
- **3-4°C below**: 90% fan (very cold - aggressive heating)
- **2-3°C below**: 75% fan (cold - strong heating)
- **1.5-2°C below**: 65% fan (moderately cold - good heating)
- **1-1.5°C below**: 55% fan (slightly cold - moderate heating)
- **0.7-1°C below**: 45% fan (just below - gentle heating)
- **0.5-0.7°C below**: 40% fan (barely below - minimal heating)

**For rooms ABOVE target** (overshot, too warm) - 5 progressive bands:
- **3°C+ above**: 5% fan (severe overshoot - near shutdown)
- **2-3°C above**: 12% fan (high overshoot - minimal airflow)
- **1-2°C above**: 22% fan (medium overshoot - reduced heating)
- **0.7-1°C above**: 30% fan (small overshoot - gentle reduction)
- **0.5-0.7°C above**: 35% fan (very small overshoot - slight reduction)

**For rooms AT TARGET** (within ±0.5°C deadband):
- **50% fan** (baseline circulation - maintains comfort)

### Main Fan Control Logic

The main AC fan speed is automatically adjusted:

- **Low Fan Speed**: All rooms at or near target (≤1°C variance, ≤0.5°C average deviation)
- **High Fan Speed**: Significant heating/cooling needed (≥2.5°C average deviation OR ≥3°C max deviation)
- **Medium Fan Speed**: All other conditions

### AC Temperature Control Logic

When automatic AC temperature control is enabled:

**Cooling Mode:**
- Aggressive cooling (rooms 2°C+ too hot): Sets AC to 19°C
- Moderate cooling (rooms 0.5-2°C too hot): Sets AC to 21°C
- Maintenance (rooms near target): Sets AC to 23°C

**Heating Mode:**
- Aggressive heating (rooms 2°C+ too cold): Sets AC to 25°C
- Moderate heating (rooms 0.5-2°C too cold): Sets AC to 23°C
- Maintenance (rooms near target): Sets AC to 21°C

## Usage

### Climate Entity

After setup, a climate entity will be created: `climate.smart_aircon_manager`

- **Current Temperature**: Shows the average temperature across all rooms
- **Target Temperature**: Set your desired temperature for the whole house
- **Mode**:
  - `Auto`: Management enabled (recommended)
  - `Cool`: Manual cooling mode
  - `Off`: Management disabled

### Diagnostic Sensors

The integration creates comprehensive diagnostic sensors:

#### Per-Room Sensors
- `sensor.{room_name}_temperature_difference` - How many degrees from target
- `sensor.{room_name}_recommendation` - System's recommended fan speed
- `sensor.{room_name}_fan_speed` - Current fan speed percentage

#### Overall System Sensors
- `sensor.optimization_status` - System status (`maintaining`, `equalizing`, `cooling`, etc.)
- `sensor.last_optimization_response` - Last optimization decision summary
- `sensor.last_data_update_time` - When coordinator last polled
- `sensor.last_optimization` - When optimizer last ran
- `sensor.next_optimization_time` - When optimizer will run next
- `sensor.error_tracking` - Error count and details
- `sensor.valid_sensors_count` - How many temperature sensors are working
- `sensor.system_status_debug` - Overall system health

#### Main Fan Sensors (if configured)
- `sensor.main_aircon_fan_speed` - Current main fan speed
- `binary_sensor.main_aircon_running` - Whether main AC is running

#### Weather Integration Sensors (if enabled)
- `sensor.outdoor_temperature` - Current outdoor temperature
- `sensor.weather_adjustment` - Temperature adjustment based on outdoor conditions

#### Scheduling Sensors (if enabled)
- `sensor.active_schedule` - Currently active schedule name
- `sensor.effective_target_temperature` - Final target after schedule and weather adjustments

#### Humidity Control Sensors (if enabled)
- `sensor.hvac_mode_recommendation` - Recommended HVAC mode based on temperature and humidity
- `sensor.house_average_humidity` - Average humidity across all rooms
- `sensor.dry_mode_active` - Whether dry mode is currently active
- `sensor.fan_only_mode_active` - Whether fan-only mode is currently active
- `sensor.comfort_index` *(NEW in v2.3.0)* - Feels-like temperature combining temp + humidity (heat index)

## Automation Example

```yaml
automation:
  - alias: "Enable aircon management when home"
    trigger:
      - platform: state
        entity_id: person.your_name
        to: "home"
    action:
      - service: climate.set_hvac_mode
        target:
          entity_id: climate.smart_aircon_manager
        data:
          hvac_mode: "auto"
      - service: climate.set_temperature
        target:
          entity_id: climate.smart_aircon_manager
        data:
          temperature: 22
```

## Troubleshooting

See [TROUBLESHOOTING.md](TROUBLESHOOTING.md) for detailed troubleshooting steps.

### Common Issues

**Integration not appearing:**
- Ensure you've copied all files correctly
- Restart Home Assistant
- Check `custom_components/smart_aircon_manager/manifest.json` exists

**System not making adjustments:**
- Check Home Assistant logs for errors
- Ensure zone fan controls are working (test manually first)
- Check "Last Optimization" sensor to see when system last ran

**Rooms not reaching target temperature:**
- Check that your main AC is set to an appropriate temperature
- Verify zone fan entities are actually changing speed
- Enable debug logging to see detailed decision-making

## Debug Logging

To enable detailed logging:

```yaml
logger:
  default: info
  logs:
    custom_components.smart_aircon_manager: debug
```

This will show:
- Optimization timing checks
- Stability checks
- AC control decisions
- Temperature setpoint changes
- All diagnostic information

## Comparison: Logic-Based vs AI-Powered

| Feature | Smart (Logic-Based) | AI (Previous Version) |
|---------|-------------------|---------------------|
| Cost | **FREE** | $1-4/month |
| Privacy | **100% Local** | Sends data to AI APIs |
| Speed | **Instant** | ~1-2 second API latency |
| Reliability | **No external dependencies** | Requires internet & API availability |
| Transparency | **Clear, documented rules** | Black-box AI decisions |
| Accuracy | **Excellent** (tuned algorithms) | **Excellent** (AI learning) |
| Customization | **Highly tunable** (thresholds) | Limited (model selection) |
| Learning | Static rules | Can adapt to usage patterns |

**Bottom Line**: The logic-based version provides excellent performance at zero cost with complete privacy and transparency. Perfect for users who want reliable, predictable HVAC control without ongoing costs.

## Privacy & Security

- All processing happens locally on your Home Assistant instance
- No external API calls or data transmission
- No telemetry or analytics
- 100% open source - you can review all code

## Support

For issues or feature requests, please open an issue on GitHub: https://github.com/overclocked15/HomeAssistant-Smart-Aircon-Manager/issues

## License

MIT License

## Migration from AI Version

If you're migrating from the AI-powered version:

1. Remove the old AI Aircon Manager integration from Settings → Devices & Services
2. Install this Smart Aircon Manager integration
3. Reconfigure with your same rooms and sensors
4. All features work the same way, just without AI API requirements!
5. You can keep your same automations - just update entity references from `ai_aircon_manager` to `smart_aircon_manager`
