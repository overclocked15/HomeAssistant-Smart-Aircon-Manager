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
- **Humidity Control**: Automatic mode switching (cool/heat/dry/fan_only) based on humidity (dry mode is suppressed in heat mode to avoid fighting the heat loop); dry mode weights airflow toward the dampest rooms
- **Occupancy Control**: Temperature setbacks for vacant rooms
- **Away Mode**: Auto vacation mode when everyone leaves (person/device tracker based)
- **Per-Room Schedule Targets**: Schedules can set different targets per room (e.g. bedrooms cooler at night)
- **Comfort Index**: Heat index combining temperature and humidity

### Smart
- **Adaptive Learning**: Learns thermal mass, cooling efficiency, and convergence rates per room
- **Room Coupling Detection**: Identifies thermally connected rooms for better balancing
- **Predictive Control**: Rate-of-change based proactive fan adjustments
- **Weather Integration**: Adjusts target based on outdoor temperature
- **Time-Based Scheduling**: Multiple schedules with day-of-week support

### Protection
- **Compressor Protection**: Prevents rapid AC cycling (basic + enhanced, including cool↔heat reversal guards)
- **Critical Room Monitoring**: Emergency alerts and auto-response for rooms with temperature limits — over-temperature (cooling response) and optional freeze protection (heating response)
- **Open Window Detection**: Pauses conditioning in rooms losing air to the outdoors
- **Fan Speed Smoothing**: Prevents oscillation with configurable smoothing
- **Runtime & Filter Tracking**: Compressor runtime and filter-maintenance sensors

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
| `reset_filter_timer` | Reset blower runtime after a filter change |

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

- **v3.0.1** (Current): Post-release code review (2 critical + 6 medium + 9 low) — AC auto-off actually works on real climate entities (hvac_mode was read from a non-existent attribute, also causing mode-set/notification spam and bypassed compressor protection), Balancing options page no longer crashes, learning analysis moved off the event loop, quick-action re-entrancy and away-mode manual cancel fixed, optimizer no longer fights critical-room emergencies, runtime tracking uses hvac_action, outlier-aware mode resolution, normalization hysteresis, drift-based balancing rates, fan percentage fallback
- **v3.0.0**: Full logic audit (13 fixes — balancing now respects per-room targets, no conditioning in unservable directions, quick-action expiry with AC off, monotonic overshoot curve, normalization no longer amplifies mild demand, and more) + feature release: occupancy/predictive/protection UI, presence-linked away mode, open-window detection, dry-mode humidity weighting, freeze protection, per-room schedule targets, fan-only idle shutdown, runtime & filter tracking
- **v2.16.3**: Pattern-sweep fixes for the same two bug families found in v2.16.2 — UI removal now works for weather entity, outdoor temp sensor, main climate, and main fan (all four were silently re-saving cleared fields); operating-mode fallback, pre-positioning, and main fan speed selection now use the global target reference instead of the weighted-average of per-room targets
- **v2.16.2**: Per-room target fixes — AC unit-level decisions (setpoint, on/off) now anchor to the global target instead of the weighted average of per-room overrides (so a high-target room override no longer keeps the AC heating past the user's global setpoint and overheating the rest of the house); per-room target override can now actually be removed from the UI (`vol.Optional(..., default=)` was silently re-saving the cleared value)
- **v2.16.1**: Production-stability audit — overnight schedules now allowed in the UI, atomic state-file writes (crash-safe persistence), HVAC mode tracker only accepts real conditioning modes at startup, climate entity rejects out-of-range setpoints, AC recommendation sensor uses per-room-aware target average, compressor state persisted on unload
- **v2.16.0**: Adaptive deadband (opt-in: widens deadband during temperature swings to reduce mode thrashing), plus three latent bug fixes — dry mode never auto-engaged on humidity-only demand, overnight schedules with day-specific days didn't activate after midnight, and quick-action sleep setback was lost across HA restarts
- **v2.15.2**: Heat/cool symmetry audit — fixed inverted-sign adaptive balancing convergence in heat mode (poorly-insulated cold rooms were getting LESS fan), mode-agnostic pre-positioning (wrong-direction rooms got over-conditioned at AC startup), and predictive damping ignoring per-room target overrides
- **v2.15.1**: Heat-mode setpoint overshoot fix — `abs(temp_diff)` in the proportional setpoint formula pushed AC setpoints above target during overshoot, causing 21°C target to drive rooms to 25–26°C
- **v2.15.0**: Heating-mode fixes (dry mode suppressed in heat mode, adaptive setpoint/efficiency mode-aware, sleep mode resolves auto), critical pre-positioning crash fix, sensor threshold consistency
- **v2.14.0**: Optimization improvements (proportional fan curve, weighted rate-of-change, dynamic prediction damping, continuous AC setpoint, smart pre-positioning, debounced cover positions, weather trend, FAN_MODE support, quick-action binary sensors, diagnostics platform, learning confidence decay)
- **v2.13.0**: Full bug & logic review (29 fixes — 1 critical + 1 high + 15 medium + 12 low)
- **v2.12.0**: 4 code review fixes, 91-test pytest suite
- **v2.11.0**: 23 audit fixes (16 medium + 7 low)
- **v2.8.2**: 10 bug fixes from full code review
- **v2.8.1**: Enhanced compressor protection
- **v2.8.0**: 15 critical logic fixes
- **v2.7.0**: Quick actions, smart learning, adaptive balancing
- **v2.6.0**: 6 features, 65-test suite
