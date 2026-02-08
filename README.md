# Smart Aircon Manager

A Home Assistant integration that intelligently manages your air conditioning system by automatically adjusting zone fan speeds based on room temperature sensors. **100% local, completely free, and private** - no AI API required.

Uses smart logic-based algorithms to achieve precise temperature control across your entire home.

## Features

### Core
- **Smart Zone Control**: 8-band temperature logic adjusts individual room fan speeds automatically
- **Temperature Equalization**: Balances temperatures across all rooms for consistent comfort
- **Automatic AC Control**: Full automation of AC on/off, fan speed, and temperature setpoint
- **Multi-Room Support**: Unlimited rooms with individual sensors and zone controls
- **Climate Entity**: Full Home Assistant climate entity with UI support

### Comfort
- **Manual Override**: Toggle switch to temporarily disable automation
- **Quick Actions**: One-tap vacation, boost, sleep, and party modes
- **Humidity Control**: Automatic mode switching (cool/heat/dry/fan_only) based on humidity
- **Occupancy Control**: Temperature setbacks for vacant rooms
- **Comfort Index**: Heat index combining temperature and humidity

### Smart
- **Adaptive Learning**: Learns thermal mass, cooling efficiency, and convergence rates per room
- **Room Coupling Detection**: Identifies thermally connected rooms for better balancing
- **Predictive Control**: Rate-of-change based proactive fan adjustments
- **Weather Integration**: Adjusts target based on outdoor temperature
- **Time-Based Scheduling**: Multiple schedules with day-of-week support

### Protection
- **Compressor Protection**: Prevents rapid AC cycling (basic + enhanced)
- **Critical Room Monitoring**: Emergency alerts and auto-response for rooms with temperature limits
- **Fan Speed Smoothing**: Prevents oscillation with configurable smoothing

## How It Works

1. Reads temperature sensors every 30 seconds (configurable)
2. Calculates optimal fan speeds using 8-band temperature logic
3. Applies smoothing, predictive adjustments, and room balancing
4. Controls AC on/off, fan speed, and temperature setpoint
5. Result: smooth temperature equilibrium across your home

**Performance**: 5-15 minutes to reach target, maintains within ±0.5°C.

## Prerequisites

- Home Assistant with custom integrations support
- Temperature sensors for each room (e.g., `sensor.bedroom_temperature`)
- Cover entities representing zone fan speed controls (e.g., `cover.bedroom_zone_fan`)

## Installation

### HACS (Recommended)

1. Open HACS > **Integrations**
2. Click three dots > **Custom repositories**
3. Add `https://github.com/overclocked15/HomeAssistant-Smart-Aircon-Manager` as category "Integration"
4. Find "Smart Aircon Manager" and click **Download**
5. Restart Home Assistant

### Manual

1. Copy `custom_components/smart_aircon_manager/` to your HA `config/custom_components/` directory
2. Restart Home Assistant

## Quick Start

1. Go to **Settings** > **Devices & Services** > **Add Integration**
2. Search for **Smart Aircon Manager**
3. Set your target temperature and (optionally) your main AC climate entity
4. Add rooms with their temperature sensors and zone fan controls
5. Done - the system starts optimizing immediately

## Documentation

| Document | Description |
|----------|-------------|
| [Configuration Reference](documentation/CONFIGURATION.md) | All configuration options with defaults and descriptions |
| [Services Reference](documentation/SERVICES.md) | All 12 services with parameters and automation examples |
| [Sensors & Entities](documentation/SENSORS.md) | Every sensor and entity the integration creates |
| [Algorithm Deep Dive](documentation/ALGORITHM.md) | How the optimization logic works |
| [Troubleshooting](documentation/TROUBLESHOOTING.md) | Common issues and debug logging |
| [Changelog](documentation/CHANGELOG.md) | Version history and release notes |
| [Dashboard Examples](examples/README.md) | Ready-to-use Lovelace dashboard templates |

## Services

| Service | Description |
|---------|-------------|
| `force_optimize` | Run optimization immediately |
| `reset_smoothing` | Clear fan speed smoothing history |
| `set_room_override` | Enable/disable control for a specific room |
| `reset_error_count` | Reset error counter |
| `vacation_mode` | Low-energy mode for extended absences |
| `boost_mode` | Aggressive cooling/heating (30 min default) |
| `sleep_mode` | Quiet operation (8 hour default) |
| `party_mode` | Equalize all rooms (2 hour default) |
| `enable_learning` | Start adaptive learning |
| `disable_learning` | Stop adaptive learning |
| `analyze_learning` | Force learning analysis |
| `reset_learning` | Clear learned data |

See [Services Reference](documentation/SERVICES.md) for full details and automation examples.

## Dashboard Examples

Ready-to-use Lovelace dashboards are in the [`examples/`](examples/) directory:

- **[dashboard.yaml](examples/dashboard.yaml)** - Comprehensive dashboard with all features
- **[dashboard-minimal.yaml](examples/dashboard-minimal.yaml)** - Clean essentials-only dashboard
- **[dashboard-enhanced.yaml](examples/dashboard-enhanced.yaml)** - Visual room map, quick actions, fan speed bars

See the [examples README](examples/README.md) for setup instructions.

## Automation Example

```yaml
automation:
  - alias: "Enable AC management when home"
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

  - alias: "Sleep mode at bedtime"
    trigger:
      - platform: time
        at: "22:00:00"
    action:
      - service: smart_aircon_manager.sleep_mode
        data:
          config_entry_id: "your_entry_id"
          duration_minutes: 480
```

## Debug Logging

```yaml
logger:
  default: info
  logs:
    custom_components.smart_aircon_manager: debug
```

## Support

- **Issues**: [GitHub Issues](https://github.com/overclocked15/HomeAssistant-Smart-Aircon-Manager/issues)
- **Discussions**: [GitHub Discussions](https://github.com/overclocked15/HomeAssistant-Smart-Aircon-Manager/discussions)
- **License**: MIT License

## Version History

See [Changelog](documentation/CHANGELOG.md) for full version history.

- **v2.8.2** (Current): 10 bug fixes from full code review
- **v2.8.1**: Enhanced compressor protection
- **v2.8.0**: 15 critical logic fixes
- **v2.7.0**: Quick actions, smart learning, adaptive balancing
- **v2.6.0**: 6 features, 65-test suite
