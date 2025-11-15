# Smart Aircon Manager - Dashboard Examples

This directory contains example Lovelace dashboards for the Smart Aircon Manager integration.

## Available Dashboards

### 1. `dashboard.yaml` - Comprehensive Dashboard
A feature-rich dashboard showcasing all capabilities of Smart Aircon Manager:
- **Manual Override Control** - Disable automatic optimization
- **Main AC Status** - Current state and recommendations
- **Room-by-Room Breakdown** - Temperature, humidity, fan speeds
- **Humidity Control** - Dehumidification and comfort metrics
- **Room Balancing** - Inter-room temperature variance
- **Occupancy-Based Control** - Vacant room setbacks
- **Weather Adjustments** - Outdoor temperature influence
- **Scheduling** - Active schedule display
- **Adaptive Learning** - Confidence, thermal mass, efficiency metrics
- **System Diagnostics** - Performance and error tracking

### 2. `dashboard-minimal.yaml` - Minimal Dashboard
A clean, simple dashboard with just the essentials:
- Manual override toggle
- Current temperature and target
- Main AC control
- Room temperatures
- Basic status information

## Setup Instructions

### Step 1: Find Your Config Entry ID

Your config entry ID is required for some service calls. To find it:

1. Go to **Settings** → **Devices & Services**
2. Find **Smart Aircon Manager**
3. Click the **3 dots** menu → **Download Diagnostics**
4. Open the downloaded JSON file
5. Look for `"entry_id"` near the top - this is your config entry ID

Example: `a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6`

### Step 2: Customize Entity Names

Replace placeholder entity names with your actual entities:

**Climate Entities:**
- `YOUR_MAIN_CLIMATE_ENTITY` → e.g., `climate.living_room_ac`

**Temperature Sensors:**
- `YOUR_LIVING_ROOM_TEMP_SENSOR` → e.g., `sensor.living_room_temperature`
- `YOUR_BEDROOM_TEMP_SENSOR` → e.g., `sensor.bedroom_temperature`
- `YOUR_KITCHEN_TEMP_SENSOR` → e.g., `sensor.kitchen_temperature`

**Fan Entities:**
- `YOUR_LIVING_ROOM_FAN` → e.g., `fan.living_room_ceiling_fan`
- `YOUR_BEDROOM_FAN` → e.g., `fan.bedroom_ceiling_fan`

**Occupancy Sensors (if enabled):**
- `YOUR_LIVING_ROOM_OCCUPANCY` → e.g., `binary_sensor.living_room_motion`

### Step 3: Remove Unused Sections

Comment out or delete sections for features you haven't enabled:

- **Humidity Control** - Remove if `enable_humidity_control: false`
- **Occupancy** - Remove if `enable_occupancy_control: false`
- **Weather Adjustment** - Remove if `enable_weather_adjustment: false`
- **Scheduling** - Remove if `enable_scheduling: false`

### Step 4: Add to Your Dashboard

**Option A: New Dashboard**
1. Go to **Settings** → **Dashboards**
2. Click **Add Dashboard**
3. Name it "Air Conditioning"
4. Click **Take Control** (to enable YAML mode)
5. Paste the dashboard YAML

**Option B: Existing Dashboard**
1. Edit your dashboard
2. Click **Add Card** → **Manual Card**
3. Paste the dashboard YAML

## Manual Override Feature

### What is Manual Override?

The **Manual Override** switch allows you to temporarily disable automatic optimization, giving you full manual control of your AC and fans.

**When enabled:**
- ✅ Automatic optimization is **disabled**
- ✅ You can manually control AC and fans
- ✅ System still collects data for learning
- ✅ Sensors continue to update

**When disabled:**
- ✅ Automatic optimization is **active**
- ✅ System controls AC and fans based on logic
- ✅ Recommendations are automatically applied

### Using Manual Override

**In the Dashboard:**
```yaml
entity: switch.smart_aircon_manager_manual_override
```
Simply toggle the switch on/off.

**Via Service Call:**
```yaml
service: switch.turn_on
target:
  entity_id: switch.smart_aircon_manager_manual_override
```

**In Automations:**
```yaml
# Enable manual override when guests arrive
automation:
  - alias: "AC Manual Mode for Guests"
    trigger:
      - platform: state
        entity_id: binary_sensor.front_door
        to: "on"
    action:
      - service: switch.turn_on
        target:
          entity_id: switch.smart_aircon_manager_manual_override
      - service: notify.mobile_app
        data:
          message: "AC switched to manual mode for guest comfort"

  # Disable override at night
  - alias: "AC Auto Mode at Night"
    trigger:
      - platform: time
        at: "22:00:00"
    action:
      - service: switch.turn_off
        target:
          entity_id: switch.smart_aircon_manager_manual_override
```

## Available Services

You can add buttons to call these services directly from your dashboard:

### Force Optimization
Run optimization immediately (bypasses normal schedule):
```yaml
service: smart_aircon_manager.force_optimize
data:
  config_entry_id: YOUR_CONFIG_ENTRY_ID  # Optional - runs all if omitted
```

### Reset Learning
Clear all learning data (or for specific room):
```yaml
service: smart_aircon_manager.reset_learning
data:
  config_entry_id: YOUR_CONFIG_ENTRY_ID
  room_name: living_room  # Optional - resets all if omitted
```

### Analyze Learning
Manually trigger learning analysis:
```yaml
service: smart_aircon_manager.analyze_learning
data:
  config_entry_id: YOUR_CONFIG_ENTRY_ID
```

### Reset Smoothing
Clear fan speed smoothing cache:
```yaml
service: smart_aircon_manager.reset_smoothing
data:
  config_entry_id: YOUR_CONFIG_ENTRY_ID
```

### Set Room Override
Enable/disable optimization for specific room:
```yaml
service: smart_aircon_manager.set_room_override
data:
  config_entry_id: YOUR_CONFIG_ENTRY_ID
  room_name: bedroom
  enabled: false  # Disable optimization for this room
```

## Custom Cards (Optional)

For enhanced visuals, consider these custom Lovelace cards:

### Fold Entity Row
Collapsible rows for cleaner organization.
```
https://github.com/thomasloven/lovelace-fold-entity-row
```

### Mini Graph Card
Beautiful temperature history graphs.
```
https://github.com/kalkih/mini-graph-card
```

### Mushroom Cards
Modern, mobile-optimized card design.
```
https://github.com/piitaya/lovelace-mushroom
```

### Layout Card
Advanced grid and masonry layouts.
```
https://github.com/thomasloven/lovelace-layout-card
```

Install via HACS: **HACS** → **Frontend** → **Explore & Download Repositories**

## Troubleshooting

### Entities Show as "Unavailable"

**Check:**
1. Integration is properly configured (Settings → Devices & Services)
2. All temperature sensors are working
3. Main climate entity exists and is responding
4. Room names in dashboard match exactly with your configuration

### Manual Override Switch Not Found

**Possible causes:**
1. Integration version < 2.4.6 (update required)
2. Integration not reloaded after update
3. Switch platform not loaded

**Fix:**
```
Settings → Devices & Services → Smart Aircon Manager → 3 dots → Reload
```

### Dashboard Layout Looks Wrong

**Check:**
1. Custom cards are installed (if used)
2. Theme supports state colors
3. Mobile view may need different layout
4. Browser cache cleared

### Sensor Names Don't Match

Sensor naming format:
```
sensor.smart_aircon_manager_{room_name}_{sensor_type}
```

Example: `sensor.smart_aircon_manager_living_room_temperature_difference`

Room names use lowercase with underscores. If your room is configured as "Living Room", the sensor will be `living_room`.

## Advanced Customization

### Adding Temperature History Graph

```yaml
type: custom:mini-graph-card
entities:
  - entity: sensor.smart_aircon_manager_house_average_temperature
    name: Average
    color: blue
  - entity: sensor.smart_aircon_manager_effective_target_temperature
    name: Target
    color: red
    show_line: true
    show_points: false
  - entity: sensor.YOUR_LIVING_ROOM_TEMP_SENSOR
    name: Living Room
    color: green
  - entity: sensor.YOUR_BEDROOM_TEMP_SENSOR
    name: Bedroom
    color: orange
hours_to_show: 24
line_width: 2
font_size: 75
animate: true
show:
  labels: true
  legend: true
```

### Conditional Cards Based on HVAC Mode

```yaml
type: conditional
conditions:
  - entity: sensor.smart_aircon_manager_hvac_mode_recommendation
    state: "cool"
card:
  type: markdown
  content: |
    ## Cooling Active
    System is actively cooling your home.
    Current mode: **{{ states('sensor.smart_aircon_manager_hvac_mode_recommendation') }}**
```

### Color-Coded Temperature Cards

```yaml
type: entity
entity: sensor.smart_aircon_manager_house_average_temperature
state_color: true
card_mod:
  style: |
    :host {
      --paper-item-icon-color:
        {% set temp = states('sensor.smart_aircon_manager_house_average_temperature') | float %}
        {% if temp < 20 %} blue
        {% elif temp < 22 %} green
        {% elif temp < 24 %} orange
        {% else %} red
        {% endif %};
    }
```

## Example Automations

### Notify When Manual Override Active Too Long

```yaml
automation:
  - alias: "AC Manual Override Reminder"
    trigger:
      - platform: state
        entity_id: switch.smart_aircon_manager_manual_override
        to: "on"
        for:
          hours: 4
    action:
      - service: notify.mobile_app
        data:
          title: "AC Manual Mode Active"
          message: "Smart Aircon has been in manual mode for 4 hours. Switch back to auto?"
          data:
            actions:
              - action: AC_AUTO_MODE
                title: "Enable Auto Mode"

  - alias: "AC Manual Override Restore Auto"
    trigger:
      - platform: event
        event_type: mobile_app_notification_action
        event_data:
          action: AC_AUTO_MODE
    action:
      - service: switch.turn_off
        target:
          entity_id: switch.smart_aircon_manager_manual_override
```

### Auto-Enable Manual Override for Movie Time

```yaml
automation:
  - alias: "AC Manual for Movies"
    trigger:
      - platform: state
        entity_id: media_player.living_room_tv
        to: "playing"
    condition:
      - condition: template
        value_template: "{{ state_attr('media_player.living_room_tv', 'media_content_type') == 'movie' }}"
    action:
      - service: switch.turn_on
        target:
          entity_id: switch.smart_aircon_manager_manual_override
      - service: climate.set_temperature
        target:
          entity_id: climate.main_ac
        data:
          temperature: 22
      - delay:
          hours: 3
      - service: switch.turn_off
        target:
          entity_id: switch.smart_aircon_manager_manual_override
```

## Support

For issues or questions:
- **GitHub Issues**: https://github.com/overclocked15/HomeAssistant-Smart-Aircon-Manager/issues
- **Discussions**: https://github.com/overclocked15/HomeAssistant-Smart-Aircon-Manager/discussions
- **Documentation**: Check the main README.md

## Contributing

Have a better dashboard layout? Share it!
Submit a PR with your dashboard example to help other users.
