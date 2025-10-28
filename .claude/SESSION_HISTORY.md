# Claude Code Session History - AI Aircon Manager

## Latest Session: 2025-10-25

### Current State
- **Latest Version:** v1.5.0
- **Status:** Released and published to GitHub
- **Branch:** main
- **Last Commit:** 71a037b - "Add hysteresis for AC auto on/off control v1.5.0"

### Recent Work Completed

#### 1. Separate Data Polling from AI Optimization (v1.3.8)
- Poll sensor data every 30 seconds (fast, cheap, local)
- Run AI optimization every 5 minutes (expensive, configurable)
- Persist AI recommendations between polls to prevent "unknown" states
- **Files Changed:** const.py, optimizer.py, __init__.py, manifest.json

#### 2. Debug Logging (v1.3.9)
- Added comprehensive logging to track AI optimization vs data collection cycles
- Shows when using cached recommendations during data-only polls
- Helps diagnose issues where entities show empty/unknown values

#### 3. Bug Fixes (v1.3.10 - v1.3.11)
- Fixed AttributeError: `last_update_success_time` doesn't exist in DataUpdateCoordinator
- Fixed deprecated `self.config_entry` explicit setting in OptionsFlowHandler
- Changed `last_update_success_time` to `last_update_success` in sensor.py

#### 4. HVAC Mode-Aware Main Fan Speed (v1.4.0)
**User Issue:** "Whole home at 21°C, target 22°C, in cool mode. Main fan shows 'high' but should be 'low' since temps are below target."

**Fix:** Main fan speed now considers HVAC mode and temperature direction:
- Cool mode, temps ABOVE target → High fan (need cooling)
- Cool mode, temps BELOW target → Low fan (don't cool)
- Heat mode, temps BELOW target → High fan (need heating)
- Heat mode, temps ABOVE target → Low fan (don't heat)

**Files Changed:** optimizer.py (lines 535-621), sensor.py (lines 458-500)

#### 5. Directionally-Aware Room Fan Speeds (v1.4.1)
**User Issue:** "Main bedroom is -3.9°C below target but AI set fan to 100%. In cool mode, this room is already too cold and should be at LOW fan speed."

**Fix:** Completely rewrote AI prompt to emphasize temperature direction:
- Shows temperature difference with sign: "+2.5°C" or "-3.9°C"
- Shows status: "TOO HOT", "TOO COLD", "AT TARGET"
- Explicit strategy tables for cooling vs heating
- Mode-specific explanations about what each room needs

**Files Changed:** optimizer.py `_build_optimization_prompt()` (lines 370-469)

#### 6. Hysteresis for AC Auto On/Off (v1.5.0) - LATEST
**User Request:** "I don't want my AC to stop-start. It should turn off when avg is 2°C below target AND no rooms above target. Stay off until 1°C above target. Prevents rapid cycling on hot days."

**Implementation:**
- **Cooling Mode:**
  - Turn ON: avg ≥ target + 1.0°C
  - Turn OFF: avg ≤ target - 2.0°C AND all rooms ≤ target
- **Heating Mode:**
  - Turn ON: avg ≤ target - 1.0°C
  - Turn OFF: avg ≥ target + 2.0°C AND all rooms ≥ target

**Files Changed:** const.py, optimizer.py `_check_if_ac_needed()` (lines 715-813), __init__.py

### Known Issues
None currently reported.

### User Configuration
- **HVAC Mode:** Cool
- **Target Temperature:** 22°C
- **Rooms:** Main Bedroom, and others
- **Main Climate Entity:** Configured
- **Main Fan Entity:** Configured
- **Auto Control Main AC:** User asked about this feature

### User Preferences
1. Prefers updates via HACS (GitHub releases)
2. Wants clean commit history with detailed release notes
3. Values detailed explanations of how features work
4. Appreciates emoji-free, professional communication
5. Likes specific examples and scenarios in explanations

### Architecture Overview

#### Key Files
- **const.py:** Configuration constants and defaults
- **optimizer.py:** Core AI optimization logic, AC control, main fan control
- **sensor.py:** All sensor entities (diagnostic, debug, status)
- **binary_sensor.py:** Main Aircon Running sensor
- **climate.py:** Climate entity for integration control
- **config_flow.py:** Configuration and options flow UI
- **__init__.py:** Integration setup and coordinator

#### Key Concepts
- **Deadband:** Acceptable temperature range around target (default 0.5°C)
- **Hysteresis:** Different thresholds for turning AC on vs off (prevents cycling)
- **Data Polling:** Frequent sensor reads (30s) separate from AI optimization (5min)
- **Room Overrides:** Disable AI control for specific rooms
- **Main Fan Control:** Automatically adjust main AC fan speed based on system state

### Version History (Recent)
- v1.5.0 (Current) - Hysteresis for AC auto control
- v1.4.1 - Directionally-aware room fan speeds AI prompt
- v1.4.0 - HVAC mode-aware main fan speed logic
- v1.3.11 - Fix deprecated config_entry warning
- v1.3.10 - Fix AttributeError crash
- v1.3.9 - Debug logging
- v1.3.8 - Separate data polling from AI optimization

### Next Steps / Potential Enhancements
1. **Make hysteresis thresholds configurable** - Add to options flow UI
2. **Add configuration for data polling interval** - Currently hardcoded at 30s
3. **Temperature unit handling** - Currently supports °F to °C conversion
4. **Enhanced room override UI** - Potentially add more granular controls

### Testing Checklist for User
When updating to v1.5.0:
- [ ] Update via HACS to v1.5.0
- [ ] Restart Home Assistant or reload integration
- [ ] Check logs for hysteresis decision logging
- [ ] Verify main fan speed shows "low" when temps below target in cool mode
- [ ] Verify room fan speeds are directionally appropriate
- [ ] Test auto AC on/off (if enabled) to see hysteresis in action

### Important Notes
- User deploys via HACS, needs GitHub releases for updates
- All changes must be committed, pushed, and released before user can test
- User values detailed release notes explaining the "why" not just the "what"
- Integration is at v1.5.0 with comprehensive HVAC control features

### Commands for Next Session
```bash
# Check current status
git status
git log --oneline -5

# See latest release
gh release list

# Continue development from v1.5.0
```

### Questions User Might Ask Next
Based on the conversation flow:
1. How to configure the hysteresis thresholds?
2. Can the data polling interval be adjusted?
3. How to add more rooms after initial setup?
4. How to monitor AI optimization decisions?
5. What happens when AC is manually controlled vs auto-controlled?

---

## Session Context for Claude

When resuming, remember:
- User is technical and appreciates detailed explanations
- Always commit → push → create GitHub release for user to test via HACS
- Use version bumping: patch for fixes, minor for features, major for breaking changes
- Provide real-world examples and scenarios
- No emojis in code or documentation unless specifically requested
- Focus on HVAC best practices and energy efficiency
