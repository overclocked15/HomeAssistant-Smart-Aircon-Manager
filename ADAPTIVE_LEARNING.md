# Adaptive Learning Concept for Smart Aircon Manager

## Overview

Adaptive learning would allow the Smart Aircon Manager to **automatically tune its parameters** based on observed performance over time. This is 100% logic-based using statistical analysis - **no AI/LLMs involved**.

## Core Concept

The system would track how well different settings perform, then gradually adjust parameters to optimize for:
- Temperature stability
- Energy efficiency
- User comfort
- Fast convergence to target

## What Would Be Learned

### 1. Room-Specific Thermal Characteristics
**Problem**: Every room behaves differently due to:
- Size and insulation
- Sun exposure
- Proximity to AC unit
- Furniture and occupancy

**Solution**: Track per-room metrics:
```python
{
  "living_room": {
    "thermal_mass": 0.8,  # How slowly temp changes (0-1)
    "cooling_efficiency": 0.65,  # How well fan position affects temp
    "optimal_fan_curve": [...],  # Learned fan speed adjustments
    "sun_exposure_pattern": {...},  # Time-of-day thermal load
  }
}
```

### 2. Optimal Band Boundaries
**Problem**: Current 8-band system uses fixed thresholds (1.0°C, 1.5°C, 2.0°C, etc.)

**Solution**: Learn optimal boundaries per room:
- Track temperature convergence speed for each band
- Identify which bands cause oscillation
- Adjust boundaries to minimize overshoot

**Example**:
```
Room A: Heavy oscillation at 0.7°C threshold
→ Learn: Increase deadband to 0.9°C for this room

Room B: Converges too slowly with current bands
→ Learn: More aggressive fan speeds in 1.0-1.5°C range
```

### 3. Smoothing Parameters
**Problem**: Current smoothing uses fixed 70/30 weighting

**Solution**: Learn per-room smoothing needs:
- Stable rooms: More smoothing (80/20)
- Volatile rooms: Less smoothing (60/40)
- Track oscillation frequency to tune threshold

### 4. Time-Based Patterns
**Problem**: Thermal behavior changes throughout day

**Solution**: Learn time-of-day adjustments:
```python
"morning_sun_rooms": {
  "07:00-10:00": +1.5°C thermal load,  # Aggressive cooling needed
  "10:00-14:00": +2.0°C thermal load,  # Peak sun
  "14:00-18:00": +0.5°C thermal load,  # Sun moves away
}
```

### 5. Hysteresis Tuning
**Problem**: Fixed AC on/off thresholds may not suit all setups

**Solution**: Learn optimal thresholds:
- Track AC cycling frequency
- Measure energy vs comfort trade-off
- Adjust to minimize unnecessary on/off cycles

## Implementation Approach

### Phase 1: Data Collection (Passive Learning)
**Duration**: 2-4 weeks

Collect historical data without changing behavior:
```python
class PerformanceTracker:
    def track_cycle(self, room_name, data):
        """Store: timestamp, temp_before, temp_after, fan_speed,
        convergence_time, overshoot, oscillation_count"""
```

**Metrics Tracked**:
- Temperature convergence rate (°C/minute)
- Overshoot frequency and magnitude
- Oscillation count per hour
- Time in deadband vs out of deadband
- AC on/off cycle frequency

### Phase 2: Analysis & Pattern Recognition
**Statistical Analysis**:
```python
def analyze_performance():
    """
    - Calculate mean/std convergence time per band
    - Identify oscillation patterns
    - Find correlations (time of day, outdoor temp, etc.)
    - Detect thermal mass from cooldown curves
    """
```

**Pattern Detection**:
- Clustering similar thermal behaviors
- Time-series analysis for daily patterns
- Outlier detection for anomalies

### Phase 3: Parameter Tuning (Active Learning)
**Gradual Adjustments**:
```python
def apply_learned_parameters():
    """
    Apply small adjustments (max 10% change per week)
    - Update band thresholds
    - Adjust smoothing factors
    - Tune hysteresis values
    """
```

**Safety Mechanisms**:
- Max 10% parameter change per adjustment period
- Rollback if performance degrades
- User override always available
- Confidence thresholds before applying changes

### Phase 4: Continuous Improvement
**Ongoing Refinement**:
- Weekly analysis of past 7 days
- Monthly deep analysis of seasonal changes
- Automatic seasonal profile switching

## Data Storage

### Lightweight Storage Approach
```python
# Store aggregated statistics, not raw data
{
  "room_name": {
    "last_updated": "2025-01-15T10:30:00",
    "thermal_profile": {
      "thermal_mass_estimate": 0.75,
      "cooling_efficiency": 0.60,
      "learned_band_thresholds": [0.6, 0.9, 1.3, 1.7, 2.2, 2.8, 3.5],
      "optimal_smoothing": {
        "factor": 0.75,
        "threshold": 12,
      },
    },
    "time_of_day_adjustments": {
      "06-10": +1.2,
      "10-14": +1.8,
      "14-18": +0.8,
      "18-22": +0.3,
      "22-06": -0.2,
    },
    "performance_stats": {
      "avg_convergence_time_seconds": 180,
      "overshoot_rate_per_day": 0.3,
      "oscillation_rate_per_hour": 0.1,
      "confidence_score": 0.85,
    },
  }
}
```

**Storage Size**: ~5-10KB per room (vs megabytes for raw data)

## User Interface

### Configuration Options
```yaml
adaptive_learning:
  enabled: true
  learning_mode: "passive"  # passive, active, aggressive
  confidence_threshold: 0.7  # 0.0-1.0
  max_adjustment_per_week: 0.10  # 10% max change
  respect_user_overrides: true
```

### Dashboard/Sensors
New sensors to expose learned data:
- `sensor.{room}_thermal_mass`
- `sensor.{room}_cooling_efficiency`
- `sensor.{room}_learning_confidence`
- `sensor.{room}_last_tuning_date`

### Manual Controls
Services for user intervention:
- `smart_aircon_manager.reset_learning` - Start fresh
- `smart_aircon_manager.export_profile` - Save learned profile
- `smart_aircon_manager.import_profile` - Load saved profile
- `smart_aircon_manager.freeze_learning` - Stop adjustments

## Benefits

### 1. **Automatic Optimization**
- No manual tuning required
- Adapts to seasonal changes
- Handles home modifications (new furniture, insulation, etc.)

### 2. **Improved Performance**
- Faster temperature convergence
- Reduced overshoot
- Less oscillation
- Better energy efficiency

### 3. **Personalization**
- Learns your home's unique characteristics
- Adapts to your usage patterns
- Optimizes for your priorities (comfort vs efficiency)

### 4. **Seasonal Awareness**
- Automatically adjusts for summer vs winter
- Handles shoulder seasons effectively
- Learns sun patterns throughout year

## Challenges & Solutions

### Challenge 1: Data Quality
**Problem**: Bad sensor data corrupts learning

**Solution**:
- Robust outlier detection
- Validation against physical constraints
- Confidence scoring system
- Gradual trust building

### Challenge 2: Changing Conditions
**Problem**: Home changes (renovations, new furniture, etc.)

**Solution**:
- Detect performance degradation
- Automatic re-learning triggers
- User notification of significant changes
- Manual reset option

### Challenge 3: Computational Load
**Problem**: Analysis could be CPU intensive

**Solution**:
- Run analysis during low-activity hours (3-4 AM)
- Aggregate data to reduce processing
- Incremental updates vs full recalculation
- Configurable analysis frequency

### Challenge 4: User Trust
**Problem**: Users may not trust automatic changes

**Solution**:
- Transparent logging of all adjustments
- Before/after performance comparison
- Easy rollback mechanism
- Gradual, conservative changes only

## Implementation Timeline

### MVP (v2.0.0) - 2-3 weeks
- Basic data collection
- Simple performance tracking
- Export/import profiles

### Full Implementation (v2.1.0) - 4-6 weeks
- Statistical analysis
- Automatic parameter tuning
- Time-based patterns

### Advanced Features (v2.2.0+) - Ongoing
- Seasonal profiles
- Multi-zone optimization
- Predictive adjustments
- Energy cost optimization

## Example Scenarios

### Scenario 1: New Installation
```
Week 1: Passive learning, default parameters
Week 2: Basic thermal mass estimation
Week 3: First small adjustments (±5%)
Week 4: Confidence reaches 0.6, moderate adjustments
Week 8: Confidence 0.85, fully optimized
```

### Scenario 2: Seasonal Change
```
Summer → Fall transition detected (outdoor temps dropping)
- Gradual reduction in cooling aggressiveness
- Adjust deadband for new thermal loads
- Switch from summer to fall profile over 2 weeks
```

### Scenario 3: Renovation Impact
```
User adds insulation to room
- System detects slower temperature changes
- Thermal mass estimate increases
- Automatically reduces fan speeds
- Adjusts convergence expectations
```

## Conclusion

Adaptive learning would transform Smart Aircon Manager from a **configurable system** to a **self-optimizing system**. It maintains the core principle of logic-based control while adding intelligence through statistical learning rather than AI.

**Key Principle**: Learn from data, not from AI. Use math and statistics to continuously improve performance without external dependencies.

---

**Status**: Concept document for future implementation
**Target Version**: v2.0.0 or later
**Dependencies**: None (100% local, no external APIs)
