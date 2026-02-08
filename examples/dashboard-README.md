# Enhanced Dashboard Setup Guide

This guide will help you set up the enhanced dashboard for Smart Aircon Manager v2.7.0+.

## Overview

The enhanced dashboard provides:
- **Quick Action Buttons**: One-tap access to vacation/boost/sleep/party modes
- **Visual Room Temperature Map**: Color-coded room status at a glance
- **System Overview Gauges**: House average temperature and room variance
- **Fan Speed Visualization**: Bar chart showing fan speeds across all rooms
- **Learning Analytics**: Comprehensive view of adaptive learning progress
- **Schedule Management**: View active and upcoming schedules
- **Advanced Controls**: Direct access to all services and settings

## Prerequisites

### Required Custom Cards

The enhanced dashboard uses three custom cards that must be installed via HACS:

1. **Mushroom Cards** - Modern, minimalist card designs
   - Repository: https://github.com/piitaya/lovelace-mushroom
   - HACS Installation: `HACS → Frontend → Explore & Download Repositories → Search "Mushroom"`

2. **Bar Card** - Animated bar charts
   - Repository: https://github.com/custom-cards/bar-card
   - HACS Installation: `HACS → Frontend → Explore & Download Repositories → Search "Bar Card"`

3. **Layout Card** - Grid and masonry layouts
   - Repository: https://github.com/thomasloven/lovelace-layout-card
   - HACS Installation: `HACS → Frontend → Explore & Download Repositories → Search "Layout Card"`

### How to Install HACS (if not already installed)

If you don't have HACS (Home Assistant Community Store) installed:

1. Visit https://hacs.xyz/docs/setup/download
2. Follow the installation instructions
3. Restart Home Assistant
4. Add HACS integration via Settings → Devices & Services

## Installation Steps

### Step 1: Install Required Custom Cards

1. Open Home Assistant
2. Go to **HACS** (in the sidebar)
3. Click **Frontend**
4. Click **Explore & Download Repositories**
5. Search for and install each of the following:
   - **Mushroom**
   - **Bar Card**
   - **Layout Card**
6. After each installation, click **Reload** when prompted
7. Clear your browser cache (Ctrl+Shift+R or Cmd+Shift+R)

### Step 2: Find Your Config Entry ID

You need to replace `YOUR_CONFIG_ENTRY_ID` in the dashboard YAML with your actual config entry ID.

**Method 1: Via Developer Tools**
1. Go to **Developer Tools → States**
2. Search for any `smart_aircon_manager` entity
3. Click on any entity to view details
4. Look for `config_entry_id` in the attributes
5. Copy the value (e.g., `abc123def456789`)

**Method 2: Via Integration Settings**
1. Go to **Settings → Devices & Services**
2. Find **Smart Aircon Manager**
3. Right-click on the integration name → **Inspect Element**
4. Look for `data-entry-id` in the HTML
5. Copy the value

### Step 3: Customize Room Names

The dashboard template uses example room names (`Living Room`, `Bedroom`, `Kitchen`, `Office`). You need to update these to match your actual room configuration.

**Find your room entity names:**
1. Go to **Developer Tools → States**
2. Search for `sensor.` followed by your room names
3. Note the exact entity IDs (e.g., `sensor.master_bedroom_temperature`)

**Update the dashboard:**
Replace all instances of example room names with your actual room names in `dashboard-enhanced.yaml`:
- `living_room` → your_room_name
- `bedroom` → your_room_name
- `kitchen` → your_room_name
- `office` → your_room_name

**Example:**
```yaml
# Before
- entity: sensor.living_room_temperature
  name: Living Room

# After (if your room is named "Master Bedroom")
- entity: sensor.master_bedroom_temperature
  name: Master Bedroom
```

### Step 4: Import the Dashboard

**Option A: As a New Dashboard**
1. Copy the contents of `examples/dashboard-enhanced.yaml`
2. Go to **Settings → Dashboards**
3. Click **Add Dashboard**
4. Select **New dashboard from scratch**
5. Name it "Smart Aircon Manager"
6. After creation, click the ⋮ menu → **Edit Dashboard**
7. Click **Raw configuration editor**
8. Paste the customized YAML
9. Click **Save**

**Option B: As a New View in Existing Dashboard**
1. Open your existing dashboard
2. Click **Edit Dashboard**
3. Click **+ Add View**
4. Click **Raw configuration editor**
5. Paste just the `views` section from `dashboard-enhanced.yaml`
6. Click **Save**

### Step 5: Test the Dashboard

1. Navigate to your new dashboard
2. Verify all cards render correctly
3. Test a quick action button (e.g., Vacation Mode)
4. Check that room temperature colors update based on deviation from target
5. Verify fan speed bars display correctly

## Troubleshooting

### Cards Not Rendering

**Problem:** Cards show "Custom element doesn't exist: custom:mushroom-template-card"

**Solution:**
1. Ensure custom cards are installed via HACS
2. Hard refresh browser (Ctrl+Shift+R)
3. Check browser console for errors (F12)
4. Try clearing Home Assistant cache: `Configuration → System → Clear Cache`

### Entities Not Found

**Problem:** Cards show "Entity not available: sensor.living_room_temperature"

**Solution:**
1. Verify room names match your configuration exactly
2. Check entity IDs in Developer Tools → States
3. Ensure Smart Aircon Manager integration is running
4. Check that rooms are configured in the integration settings

### Quick Action Buttons Don't Work

**Problem:** Clicking buttons does nothing or shows error

**Solution:**
1. Verify you replaced `YOUR_CONFIG_ENTRY_ID` with your actual ID
2. Check that services are available in Developer Tools → Services
3. Look for `smart_aircon_manager.vacation_mode` etc.
4. Ensure you're running Smart Aircon Manager v2.7.0 or later

### Template Errors

**Problem:** Cards show template rendering errors

**Solution:**
1. Check that all sensor entities exist for your rooms
2. Verify template syntax in the YAML (no extra spaces/tabs)
3. Test templates in Developer Tools → Template
4. Ensure numeric sensors return valid numbers (not "unknown" or "unavailable")

## Dashboard Customization

### Adding More Rooms

To add additional rooms to the temperature map:

1. Copy an existing room card block
2. Update entity IDs to match your new room
3. Change the icon to suit the room (mdi:bed, mdi:sofa, mdi:desk, etc.)
4. Add to the layout-card grid

Example:
```yaml
- type: custom:mushroom-template-card
  primary: Garage
  secondary: |
    {{ states('sensor.garage_temperature') }}°C
    (Target: {{ states('sensor.garage_target_temperature') }}°C)
  icon: mdi:garage
  icon_color: |
    {% set temp = states('sensor.garage_temperature') | float(0) %}
    {% set target = states('sensor.garage_target_temperature') | float(22) %}
    {% set diff = temp - target %}
    {% if diff > 2 %}
      red
    {% elif diff > 1 %}
      orange
    {% elif diff > 0.5 %}
      yellow
    {% elif diff < -2 %}
      blue
    {% elif diff < -1 %}
      light-blue
    {% else %}
      green
    {% endif %}
  badge_icon: mdi:fan
  badge_color: |
    {% set speed = states('sensor.garage_fan_speed') | int(0) %}
    {% if speed > 70 %}
      red
    {% elif speed > 30 %}
      yellow
    {% else %}
      green
    {% endif %}
```

### Adjusting Color Thresholds

Temperature color coding can be customized in the template:

```yaml
{% if diff > 2 %}        # More than 2°C above target = RED
  red
{% elif diff > 1 %}      # 1-2°C above target = ORANGE
  orange
{% elif diff > 0.5 %}    # 0.5-1°C above target = YELLOW
  yellow
{% elif diff < -2 %}     # More than 2°C below target = BLUE
  blue
{% elif diff < -1 %}     # 1-2°C below target = LIGHT BLUE
  light-blue
{% else %}               # Within ±0.5°C of target = GREEN
  green
{% endif %}
```

Adjust the threshold values to suit your preferences.

### Changing Icons

MDI (Material Design Icons) are used throughout. Browse available icons at:
https://materialdesignicons.com/

Common room icons:
- `mdi:sofa` - Living room
- `mdi:bed` - Bedroom
- `mdi:silverware-fork-knife` - Kitchen/Dining
- `mdi:desk` - Office
- `mdi:bathtub` - Bathroom
- `mdi:garage` - Garage
- `mdi:home` - Generic room

### Gauge Customization

Adjust gauge ranges and colors:

```yaml
- type: gauge
  entity: sensor.smart_aircon_manager_house_avg_temperature
  name: House Average
  min: 18          # Minimum display value
  max: 28          # Maximum display value
  severity:
    green: 20      # Green below 20°C
    yellow: 23     # Yellow between 20-23°C
    red: 26        # Red above 26°C
  needle: true
```

## Fallback: Standard Cards Only

If you prefer not to install custom cards, here's a simplified version using only standard Home Assistant cards:

```yaml
title: Smart Aircon Manager (Standard)
views:
  - title: Overview
    cards:
      # Quick Actions
      - type: entities
        title: Quick Actions
        entities:
          - type: button
            name: Vacation Mode
            icon: mdi:bag-checked
            tap_action:
              action: call-service
              service: smart_aircon_manager.vacation_mode
              data:
                config_entry_id: YOUR_CONFIG_ENTRY_ID
          - type: button
            name: Boost Mode
            icon: mdi:rocket-launch
            tap_action:
              action: call-service
              service: smart_aircon_manager.boost_mode
              data:
                config_entry_id: YOUR_CONFIG_ENTRY_ID
                duration_minutes: 30

      # Room Temperatures
      - type: entities
        title: Room Temperatures
        entities:
          - entity: sensor.living_room_temperature
          - entity: sensor.bedroom_temperature
          - entity: sensor.kitchen_temperature
          - entity: sensor.office_temperature

      # Fan Speeds
      - type: entities
        title: Fan Speeds
        entities:
          - entity: sensor.living_room_fan_speed
          - entity: sensor.bedroom_fan_speed
          - entity: sensor.kitchen_fan_speed
          - entity: sensor.office_fan_speed
```

## Advanced Features

### Conditional Cards

Show cards only when certain conditions are met:

```yaml
- type: conditional
  conditions:
    - entity: sensor.smart_aircon_manager_quick_action_mode
      state_not: "off"
  card:
    type: markdown
    content: |
      ## Active Mode Alert
      Quick action mode is currently active!
```

### Auto-Entities

Use the `auto-entities` custom card to dynamically populate room lists:

```yaml
- type: custom:auto-entities
  card:
    type: entities
    title: All Room Temperatures
  filter:
    include:
      - entity_id: "sensor.*_temperature"
        integration: smart_aircon_manager
```

## Support

If you encounter issues with the dashboard:

1. Check the Home Assistant logs: **Settings → System → Logs**
2. Verify Smart Aircon Manager version: Should be v2.7.0 or later
3. Test entities in Developer Tools → States
4. File an issue: https://github.com/overclocked15/HomeAssistant-Smart-Aircon-Manager/issues

## Additional Resources

- Home Assistant Dashboard Documentation: https://www.home-assistant.io/dashboards/
- Mushroom Cards Documentation: https://github.com/piitaya/lovelace-mushroom/wiki
- Bar Card Documentation: https://github.com/custom-cards/bar-card
- Layout Card Documentation: https://github.com/thomasloven/lovelace-layout-card
- Material Design Icons: https://materialdesignicons.com/

## Example Automations

### Auto-Enable Vacation Mode

```yaml
automation:
  - alias: "Enable Vacation Mode When Away"
    trigger:
      - platform: state
        entity_id: input_boolean.vacation_mode
        to: "on"
    action:
      - service: smart_aircon_manager.vacation_mode
        data:
          config_entry_id: YOUR_CONFIG_ENTRY_ID
          enabled: true

  - alias: "Disable Vacation Mode When Home"
    trigger:
      - platform: state
        entity_id: input_boolean.vacation_mode
        to: "off"
    action:
      - service: smart_aircon_manager.vacation_mode
        data:
          config_entry_id: YOUR_CONFIG_ENTRY_ID
          enabled: false
```

### Boost Mode Before Arriving Home

```yaml
automation:
  - alias: "Boost AC Before Arrival"
    trigger:
      - platform: zone
        entity_id: person.john
        zone: zone.home
        event: enter
    condition:
      - condition: numeric_state
        entity_id: sensor.smart_aircon_manager_house_avg_temperature
        above: 26
    action:
      - service: smart_aircon_manager.boost_mode
        data:
          config_entry_id: YOUR_CONFIG_ENTRY_ID
          duration_minutes: 30
```

### Sleep Mode at Bedtime

```yaml
automation:
  - alias: "Enable Sleep Mode at Night"
    trigger:
      - platform: time
        at: "22:00:00"
    action:
      - service: smart_aircon_manager.sleep_mode
        data:
          config_entry_id: YOUR_CONFIG_ENTRY_ID
          duration_minutes: 480  # 8 hours
```

## Mobile Dashboard Tips

For mobile devices, consider:

1. **Reduce Grid Columns**: Change `grid-template-columns: 1fr 1fr` for better mobile layout
2. **Use Vertical Stacks**: Replace horizontal-stack with vertical-stack on mobile
3. **Conditional Display**: Hide complex cards on mobile using `conditional` cards
4. **Compact View**: Use `state-label` entity rows for more compact display

Example mobile-friendly adjustment:

```yaml
- type: custom:layout-card
  layout_type: grid
  layout:
    # Desktop: 3 columns, Mobile: 2 columns
    grid-template-columns: repeat(auto-fit, minmax(150px, 1fr))
  cards:
    # Room cards here
```

---

**Dashboard Version:** 1.0
**Compatible with:** Smart Aircon Manager v2.7.0+
**Last Updated:** 2026-02-08
