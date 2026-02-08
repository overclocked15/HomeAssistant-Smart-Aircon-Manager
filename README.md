# Smart Aircon Manager

A Home Assistant integration that intelligently manages your air conditioning system by automatically adjusting zone fan speeds based on room temperature sensors. **100% local, completely free, and private** - no AI API required!

Uses smart logic-based algorithms to achieve precise temperature control across your entire home.

## Features

### Core Capabilities
- **Smart Zone Control**: Automatically adjusts individual room fan speeds using 8-band temperature logic
- **Temperature Equalization**: Balances temperatures across all rooms for consistent comfort
- **Automatic AC Control**: Full automation of AC on/off, fan speed (low/medium/high), and temperature setpoint
- **Multi-Room Support**: Unlimited rooms with individual temperature sensors and zone controls
- **100% Local & Free**: No external API calls, completely private, zero cost
- **Climate Entity Integration**: Full Home Assistant climate entity with UI support
- **Comprehensive Diagnostics**: 20+ sensors for monitoring, troubleshooting, and automation
- **Flexible Configuration**: Easy UI-based setup with reconfiguration options

### Advanced Features
- **Manual Override**: Toggle switch to temporarily disable automation while retaining manual control
- **Room Overrides**: Selectively disable control for specific rooms
- **Heating/Cooling Modes**: Full support for both modes with auto-detection from main climate entity
- **Hysteresis Control**: Prevents rapid AC cycling and mode switching to reduce equipment wear
- **Startup Protection**: Grace period during HA startup to prevent false alarms
- **Comfort Index**: Heat index calculation combining temperature and humidity for "feels-like" temperature
- **Occupancy Control**: Automatic temperature setbacks (±2°C) for vacant rooms with configurable sensors and timeout
- **Persistent Notifications**: Optional alerts for important events

### Smart Automation
- **Weather Integration**: Adjusts target temperature based on outdoor conditions (hot weather: cooler, cold weather: warmer)
- **Time-Based Scheduling**: Multiple schedules with day-of-week and time-range support (including cross-midnight)
- **Progressive Overshoot Handling**: Gradual fan reduction (35% → 25% → 15% → 5%) for rooms past target
- **Predictive Control**: Rate-of-change based adjustments to prevent temperature overshoot

## How It Works

1. **Fast Monitoring**: Reads temperature sensors every 10 seconds
2. **Frequent Optimization**: Adjusts fan speeds every 30 seconds (configurable)
3. **8-Band Temperature Logic**: Calculates optimal fan speeds based on deviation from target
   - 4°C+ away: 100% fan speed (maximum)
   - 3-4°C: 90% fan speed
   - 2-3°C: 75% fan speed
   - 1.5-2°C: 65% fan speed
   - 1-1.5°C: 55% fan speed
   - 0.7-1°C: 45% fan speed
   - 0.5-0.7°C: 40% fan speed
   - Within ±0.5°C: 50% fan speed (baseline circulation)
4. **Progressive Overshoot Handling**: Gradual fan reduction for rooms past target (prevents overcooling/overheating)
5. **Automatic AC Control**: Optimizes AC temperature setpoint, fan speed, and on/off state
6. **Result**: Smooth temperature equilibrium across your entire home

### Performance
- **Response Time**: Typically 5-15 minutes to reach target temperature
- **Stability**: Maintains ±0.5°C once achieved
- **Privacy**: 100% local processing, no external API calls
- **Cost**: Completely free, no ongoing fees

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

## Algorithm Details

<details>
<summary><b>Click to expand detailed algorithm logic</b></summary>

### Cooling Mode Strategy

**Rooms ABOVE target** (need cooling):
- 4°C+ above → 100% fan (maximum cooling)
- 3-4°C → 90% fan (aggressive cooling)
- 2-3°C → 75% fan (strong cooling)
- 1.5-2°C → 65% fan (good cooling)
- 1-1.5°C → 55% fan (moderate cooling)
- 0.7-1°C → 45% fan (gentle cooling)
- 0.5-0.7°C → 40% fan (minimal cooling)

**Rooms BELOW target** (overshot - too cold):
- 3°C+ below → 5% fan (near shutdown)
- 2-3°C → 12% fan (minimal airflow)
- 1-2°C → 22% fan (reduced cooling)
- 0.7-1°C → 30% fan (gentle reduction)
- 0.5-0.7°C → 35% fan (slight reduction)

**At target** (±0.5°C): 50% fan (baseline circulation)

### Heating Mode Strategy

Same logic as cooling, but inverted (below target = more fan, above target = less fan).

### Main AC Fan Control

- **Low**: All rooms near target (≤1°C variance, ≤0.5°C avg deviation)
- **High**: Significant need (≥2.5°C avg deviation OR ≥3°C max deviation)
- **Medium**: All other conditions

### AC Temperature Control

**Cooling**: 19°C (aggressive) → 21°C (moderate) → 23°C (maintenance)
**Heating**: 25°C (aggressive) → 23°C (moderate) → 21°C (maintenance)

</details>

## Usage

### Climate Entity

After setup, a climate entity will be created: `climate.smart_aircon_manager`

- **Current Temperature**: Shows the average temperature across all rooms
- **Target Temperature**: Set your desired temperature for the whole house
- **Mode**:
  - `Auto`: Management enabled (recommended)
  - `Cool`: Manual cooling mode
  - `Off`: Management disabled

### Manual Override

A toggle switch (`switch.smart_aircon_manager_manual_override`) allows temporary manual control:

- **Enabled**: Automation disabled, manual control of AC and fans
- **Disabled**: Automatic operation resumes
- **Use Cases**: Guest visits, maintenance, testing, special events

Learning data collection continues even when override is active.

### Dashboard Examples

See the [`examples/`](examples/) directory for ready-to-use Lovelace dashboard configurations:

- **[`dashboard.yaml`](examples/dashboard.yaml)** - Comprehensive dashboard with all features
- **[`dashboard-minimal.yaml`](examples/dashboard-minimal.yaml)** - Clean, simple essentials-only dashboard
- **[`README.md`](examples/README.md)** - Complete setup guide and customization instructions

Features included in example dashboards:
- Manual override toggle
- Real-time temperature monitoring
- HVAC mode and fan speed controls
- Humidity and comfort metrics
- Learning statistics
- System diagnostics
- Service call buttons

### Diagnostic Sensors

The integration creates comprehensive diagnostic sensors:

#### Per-Room Sensors
- `sensor.{room_name}_temperature_difference` - How many degrees from target
- `sensor.{room_name}_recommendation` - System's recommended fan speed
- `sensor.{room_name}_fan_speed` - Current fan speed percentage

#### System Sensors
- `sensor.optimization_status` - Current status (maintaining, equalizing, cooling, etc.)
- `sensor.last_optimization_response` - Last decision summary
- `sensor.last_data_update_time` / `last_optimization` / `next_optimization_time` - Timing info
- `sensor.error_tracking` - Error count and details
- `sensor.valid_sensors_count` - Working temperature sensors count
- `sensor.system_status_debug` - Overall health

#### Optional Feature Sensors
- **Main Fan**: `sensor.main_aircon_fan_speed`, `binary_sensor.main_aircon_running`
- **Weather**: `sensor.outdoor_temperature`, `sensor.weather_adjustment`
- **Schedules**: `sensor.active_schedule`, `sensor.effective_target_temperature`
- **Humidity**: `sensor.hvac_mode_recommendation`, `sensor.house_average_humidity`, `sensor.comfort_index`
- **Learning**: Multiple learning performance and efficiency sensors

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

## Why Choose Smart Aircon Manager?

- ✅ **Zero Cost**: Completely free, no API fees or subscriptions
- ✅ **100% Private**: All processing happens locally, no data sent anywhere
- ✅ **Fast**: Instant decisions without external API latency
- ✅ **Reliable**: No dependency on internet or external services
- ✅ **Transparent**: Clear, documented rules you can understand and trust
- ✅ **Excellent Performance**: 5-15 min response time, ±0.5°C stability
- ✅ **Highly Tunable**: Extensive configuration options for customization

## Privacy & Security

- ✅ All processing happens locally on your Home Assistant instance
- ✅ No external API calls or data transmission
- ✅ No telemetry or analytics
- ✅ 100% open source - review all code on GitHub

## Support & Contributing

- **Issues**: [GitHub Issues](https://github.com/overclocked15/HomeAssistant-Smart-Aircon-Manager/issues)
- **Discussions**: [GitHub Discussions](https://github.com/overclocked15/HomeAssistant-Smart-Aircon-Manager/discussions)
- **License**: MIT License

## Version History

- **v2.6.0** (Current): 6 new features, 3 logic fixes, 65-test pytest suite
- **v2.5.0**: 11 bug fixes and 5 optimizations
- **v2.4.7**: Manual override switch and example dashboards
- See [CHANGELOG.md](CHANGELOG.md) for full history
