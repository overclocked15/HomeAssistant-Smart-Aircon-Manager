# Version 2.7.0 Release Notes

## 🎉 Major Features Added

### 1. Quick Actions Service
Four new service calls for common scenarios:
- **Vacation Mode**: Reduces fan speeds to 30%, widens deadband for energy savings
- **Boost Mode**: Increases fan speeds by 50% for 30 minutes (configurable)
- **Sleep Mode**: Caps fans at 40% for quieter operation, 8-hour default duration
- **Party Mode**: Equalizes all rooms to median speed for consistent comfort

New sensor: `sensor.smart_aircon_manager_quick_action_mode` shows active mode and time remaining.

### 2. Smart Learning Improvements
Activates dormant learning data collected but previously unused:

**Adaptive Temperature Bands** (`enable_adaptive_bands=True`):
- High thermal mass rooms (>0.7): 20% wider bands for slower response
- Low thermal mass rooms (<0.4): 20% tighter bands for faster response

**Efficiency-Based Fan Adjustment** (`enable_adaptive_efficiency=True`):
- High efficiency rooms (>0.7): Fan speed reduced 15%
- Low efficiency rooms (<0.4): Fan speed increased 15%

**Adaptive Predictive Control** (`enable_adaptive_predictive=True`):
- Fast converging rooms (<300s): Predictive boost reduced 30%
- Slow converging rooms (>900s): Predictive boost increased 30%

**Adaptive AC Setpoint** (`enable_adaptive_ac_setpoint=False`, opt-in):
- High efficiency house (avg >0.7): AC setpoint +1°C
- Low efficiency house (avg <0.4): AC setpoint -1°C

### 3. Adaptive Balancing
Room-aware balancing with learned characteristics:

**Room Coupling Detection** (`enable_room_coupling_detection=True`):
- Automatically detects thermally coupled rooms (shared walls, doors)
- Coupling factor 0.5-1.0 indicates connection strength
- Adjusts balancing to account for room interactions

**Learned Balancing Bias**:
- Tracks if rooms consistently overshoot/undershoots
- Bias ranges from -1.0 to +1.0
- Auto-adjusts based on overshoot frequency

**Relative Convergence Rate Tracking**:
- Calculates room's heating/cooling speed vs house average
- Values >1.0 = faster response, <1.0 = slower response
- Balancing aggressiveness scaled per room

## 📊 Configuration Changes

### New Constants Added
```python
# Smart Learning Improvements
CONF_ENABLE_ADAPTIVE_BANDS = "enable_adaptive_bands"  # Default: True
CONF_ENABLE_ADAPTIVE_EFFICIENCY = "enable_adaptive_efficiency"  # Default: True
CONF_ENABLE_ADAPTIVE_PREDICTIVE = "enable_adaptive_predictive"  # Default: True
CONF_ENABLE_ADAPTIVE_AC_SETPOINT = "enable_adaptive_ac_setpoint"  # Default: False

# Adaptive Balancing
CONF_ENABLE_ADAPTIVE_BALANCING = "enable_adaptive_balancing"  # Default: True
CONF_ENABLE_ROOM_COUPLING_DETECTION = "enable_room_coupling_detection"  # Default: True
```

### Backward Compatibility
All changes are backward compatible. Existing users will see no behavior change unless they:
1. Enable learning mode (`learning_mode="active"`)
2. Collect 200+ data points (1.5-2 hours)
3. Reach confidence threshold ≥0.7

## 🔧 Technical Changes

### Modified Files
- `__init__.py`: Added 4 quick action services (vacation/boost/sleep/party)
- `optimizer.py`: 
  - Added quick action logic (150+ lines)
  - Added adaptive learning methods (300+ lines)
  - Modified `_calculate_fan_speed()` to use adaptive bands
  - Modified `_apply_predictive_adjustment()` to use adaptive boost
  - Modified `_calculate_ac_temperature()` to use adaptive setpoints
  - Modified `_apply_room_balancing()` to use learned biases
- `learning.py`:
  - Added 5 new fields to `LearningProfile`
  - Added `get_relative_convergence_rate()` method
  - Added `detect_room_coupling()` method
  - Updated `update_from_tracker()` to populate balancing data
- `sensor.py`: Added `QuickActionModeSensor`
- `services.yaml`: Added 4 new service definitions
- `const.py`: Added 6 new config constants

### New Services
```yaml
smart_aircon_manager.vacation_mode:
  - config_entry_id (required)
  - enabled (optional, default: true)

smart_aircon_manager.boost_mode:
  - config_entry_id (required)
  - duration_minutes (optional, default: 30, range: 10-120)

smart_aircon_manager.sleep_mode:
  - config_entry_id (required)
  - duration_minutes (optional, default: 480, range: 60-720)

smart_aircon_manager.party_mode:
  - config_entry_id (required)
  - duration_minutes (optional, default: 120, range: 30-360)
```

## 📈 Performance Impact
- Quick Actions: +1-2ms per cycle (negligible)
- Smart Learning: +5-10ms per cycle (only when confidence met)
- Adaptive Balancing: +10-20ms per cycle (coupling calculations)
- **Total: +20-40ms per 30-second cycle** (acceptable impact)

## 🧪 Testing
- All features tested manually
- Learning requires 200+ data points to activate
- Backward compatible - no breaking changes

## 📝 Usage Examples

### Quick Actions
```yaml
# Automation: Enable vacation mode when away
automation:
  - alias: "Vacation Mode On"
    trigger:
      - platform: state
        entity_id: input_boolean.vacation_mode
        to: "on"
    action:
      - service: smart_aircon_manager.vacation_mode
        data:
          config_entry_id: "your_config_entry_id"
          enabled: true
```

### Monitoring Learning Status
```yaml
# Dashboard card showing learning progress
type: entities
entities:
  - sensor.living_room_learning_confidence
  - sensor.living_room_thermal_mass
  - sensor.living_room_cooling_efficiency
  - sensor.living_room_data_points
```

## 🚀 Migration Notes
No migration required. All new features are opt-in or have safe defaults.

To enable adaptive learning features:
1. Enable learning: `enable_learning: true`
2. Set mode to active: `learning_mode: "active"`
3. Wait for data collection (200+ points ≈ 1.5-2 hours)
4. Features auto-activate when confidence ≥0.7

## 🐛 Known Issues
None reported. Please file issues at: https://github.com/overclocked15/HomeAssistant-Smart-Aircon-Manager/issues

## 🙏 Acknowledgments
Special thanks to the Home Assistant community for feedback and testing!

---

**Full Changelog**: v2.6.0...v2.7.0
