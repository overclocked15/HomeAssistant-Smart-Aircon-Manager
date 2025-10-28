# Troubleshooting Guide

## Duplicate Entities with _2 Suffix

### Symptoms
Entities appear with `_2`, `_3`, etc. suffixes in Home Assistant, for example:
- `sensor.main_aircon_fan_speed_2`
- `sensor.ai_optimization_status_2`

### Cause
This happens when Home Assistant detects entities with the same `unique_id`. Common causes:

1. **Multiple Integration Instances**
   - The integration was set up more than once
   - Check: Settings → Devices & Services → AI Aircon Manager
   - If you see multiple "AI Aircon Manager" entries, you have duplicates

2. **Failed Cleanup from Previous Version**
   - Old entities weren't removed when upgrading
   - Home Assistant registry still has old entity records

### Solution

#### Option 1: Remove Duplicate Integration Instances (Recommended)
1. Go to **Settings → Devices & Services**
2. Find all **AI Aircon Manager** entries
3. Click on each one and check **Configuration → Entry ID**
4. Keep ONE instance (usually the newest), delete the others:
   - Click the **3 dots** (⋮) → **Delete**
5. Restart Home Assistant
6. Check entities - duplicates should be gone

#### Option 2: Clean Up Old Entities Manually
1. Go to **Settings → Devices & Services → Entities**
2. Search for your integration entities (e.g., "ai_aircon")
3. For each entity with `_2` suffix:
   - Click on it → Click the **gear icon** (⚙️) → **Delete**
4. Only delete entities that are:
   - Showing as "Unavailable" or "Unknown"
   - Labeled as "This entity is no longer being provided by..."

#### Option 3: Check Entity Registry
If issues persist, check the entity registry file:
1. Stop Home Assistant
2. Edit `.storage/core.entity_registry`
3. Search for duplicate `unique_id` entries with your integration's `entry_id`
4. Remove duplicate entries (backup first!)
5. Restart Home Assistant

### Diagnostic: Check Your Setup

To diagnose why duplicates keep appearing, check your logs:

1. **Enable Debug Logging** (see section below)
2. **Restart Home Assistant**
3. **Check the logs** for these lines during startup:
   ```
   Setting up AI Aircon Manager sensor platform for entry_id: <YOUR_ENTRY_ID>
   Total entities to add: <NUMBER>
   Entity unique_ids: [list of unique IDs]
   ```

4. **Look for**:
   - **Multiple entry_ids**: If you see the setup message twice with different entry_ids, you have multiple instances
   - **Duplicate unique_ids**: If the same unique_id appears more than once, that's causing the `_2` suffix

**Example of problem:**
```
Setting up AI Aircon Manager sensor platform for entry_id: abc123...
Total entities to add: 15

Setting up AI Aircon Manager sensor platform for entry_id: def456...  ← DUPLICATE INSTANCE!
Total entities to add: 15
```

**What to look for in entity unique_ids:**
Each unique_id should follow this pattern:
- `<entry_id>_<room_name>_temp_diff`
- `<entry_id>_<room_name>_ai_recommendation`
- `<entry_id>_ai_optimization_status`

If you see the same pattern with different entry_ids, you have multiple integration instances.

### Prevention
- Only set up the integration once
- Don't manually reload the integration repeatedly
- Use proper upgrade process: Update via HACS → Restart HA

### Diagnostic Logging
To see what's happening during entity creation, check logs:

```yaml
# configuration.yaml
logger:
  default: info
  logs:
    custom_components.ai_aircon_manager: debug
```

Look for these log messages:
```
Setting up AI Aircon Manager sensor platform for entry_id: abc123...
Total entities to add: 12
Entity unique_ids: ['abc123_room_temp_diff', 'abc123_room_ai_recommendation', ...]
Entities added successfully
```

If you see this TWICE with the SAME entry_id → integration loaded twice (bug)
If you see this TWICE with DIFFERENT entry_ids → multiple instances configured

---

## Room Overrides Configuration Error

### Symptoms
When trying to configure room overrides in the integration options:
- Settings → Devices & Services → AI Aircon Manager → Configure → Room Overrides
- Get an error screen or "Unknown Error Occurred"

### Cause
Room configuration data may be corrupted or missing required fields.

### Solution

#### Check Your Room Configuration
1. Go to **Settings → Devices & Services → AI Aircon Manager**
2. Click **Configure** → **Manage Rooms**
3. Verify each room has:
   - Room name
   - Temperature sensor
   - Cover entity (fan speed control)

#### Check Logs
Enable debug logging and try to access room overrides again:

```yaml
# configuration.yaml
logger:
  default: info
  logs:
    custom_components.ai_aircon_manager: debug
```

Look for:
```
WARNING - Room missing name in config: {...}
ERROR - No valid rooms found for room overrides
```

#### Fix Corrupted Room Data
If logs show rooms missing names:

1. **Re-add the problematic room:**
   - Settings → AI Aircon Manager → Configure → Manage Rooms → Remove Room
   - Then: Add New Room with all required fields

2. **Or manually fix in config:**
   - Settings → Devices & Services → AI Aircon Manager → 3 dots → Download Diagnostics
   - Check the "data" section for your room configs
   - Each room should have: `room_name`, `temperature_sensor`, `cover_entity`

### Fixed in v1.5.1
- Added error handling for missing room names
- Better logging to diagnose configuration issues
- Gracefully skips invalid rooms instead of crashing

---

## Other Common Issues

### AC Not Turning On/Off Automatically
**Check:**
1. "Automatically turn main AC on/off" is enabled in options
2. Main climate entity is configured
3. Check logs for "AC turn ON/OFF check" messages
4. Verify hysteresis thresholds (default: 1°C on, 2°C off)

### Room Fan Speeds Not Changing
**Check:**
1. Room overrides - ensure AI control is enabled for that room
2. AC is running (AI only optimizes when AC is on)
3. Temperature sensors are providing valid readings
4. Check logs for "Set cover position for [room]" messages

### Main Fan Speed Always "Unknown"
**Check:**
1. Main fan entity is configured in options
2. AC is running
3. Check logs for "Main fan → " messages
4. Verify the entity supports fan_mode or preset_mode service calls

### Sensors Showing "Unknown"
**Check:**
1. Integration has completed at least one optimization cycle (wait 5 minutes)
2. Temperature sensors are working and not "unavailable"
3. Check logs for "No valid temperature readings" warnings
4. Verify coordinator.data is being populated (check logs)

---

## Getting Help

### Before Reporting an Issue

1. **Check the logs:**
   ```yaml
   logger:
     logs:
       custom_components.ai_aircon_manager: debug
   ```

2. **Download diagnostics:**
   - Settings → Devices & Services → AI Aircon Manager
   - Click 3 dots (⋮) → Download Diagnostics

3. **Note your version:**
   - Current version shown in HACS or manifest.json

4. **Describe your setup:**
   - HVAC mode (cool/heat/auto)
   - Number of rooms
   - Whether using auto AC control
   - Which entities are affected

### Reporting Issues
GitHub Issues: https://github.com/overclocked15/HomeAssistant-AI-Aircon-Manager/issues

Include:
- Version number
- Relevant log excerpts
- Steps to reproduce
- Expected vs actual behavior
