"""Constants for the Smart Aircon Manager integration."""

DOMAIN = "smart_aircon_manager"

# Configuration keys
CONF_TARGET_TEMPERATURE = "target_temperature"
CONF_ROOM_CONFIGS = "room_configs"
CONF_ROOM_NAME = "room_name"
CONF_TEMPERATURE_SENSOR = "temperature_sensor"
CONF_COVER_ENTITY = "cover_entity"
CONF_HUMIDITY_SENSOR = "humidity_sensor"
CONF_ROOM_TARGET_TEMPERATURE = "room_target_temperature"  # Per-room target override
CONF_MAIN_CLIMATE_ENTITY = "main_climate_entity"
CONF_MAIN_FAN_ENTITY = "main_fan_entity"
CONF_UPDATE_INTERVAL = "update_interval"
CONF_TEMPERATURE_DEADBAND = "temperature_deadband"
CONF_HVAC_MODE = "hvac_mode"
CONF_AUTO_CONTROL_MAIN_AC = "auto_control_main_ac"
CONF_AUTO_CONTROL_AC_TEMPERATURE = "auto_control_ac_temperature"
CONF_ENABLE_NOTIFICATIONS = "enable_notifications"
CONF_ROOM_OVERRIDES = "room_overrides"
CONF_AC_TURN_ON_THRESHOLD = "ac_turn_on_threshold"
CONF_AC_TURN_OFF_THRESHOLD = "ac_turn_off_threshold"

# Weather integration
CONF_WEATHER_ENTITY = "weather_entity"
CONF_ENABLE_WEATHER_ADJUSTMENT = "enable_weather_adjustment"
CONF_OUTDOOR_TEMP_SENSOR = "outdoor_temp_sensor"

# Humidity control
CONF_ENABLE_HUMIDITY_CONTROL = "enable_humidity_control"
CONF_TARGET_HUMIDITY = "target_humidity"
CONF_HUMIDITY_DEADBAND = "humidity_deadband"
CONF_DRY_MODE_HUMIDITY_THRESHOLD = "dry_mode_humidity_threshold"

# Time-based scheduling
CONF_ENABLE_SCHEDULING = "enable_scheduling"
CONF_SCHEDULES = "schedules"
CONF_SCHEDULE_NAME = "schedule_name"
CONF_SCHEDULE_DAYS = "schedule_days"
CONF_SCHEDULE_START_TIME = "schedule_start_time"
CONF_SCHEDULE_END_TIME = "schedule_end_time"
CONF_SCHEDULE_TARGET_TEMP = "schedule_target_temp"
CONF_SCHEDULE_ENABLED = "schedule_enabled"

# Advanced settings - magic numbers
CONF_MAIN_FAN_HIGH_THRESHOLD = "main_fan_high_threshold"
CONF_MAIN_FAN_MEDIUM_THRESHOLD = "main_fan_medium_threshold"
CONF_WEATHER_INFLUENCE_FACTOR = "weather_influence_factor"
CONF_OVERSHOOT_TIER1_THRESHOLD = "overshoot_tier1_threshold"
CONF_OVERSHOOT_TIER2_THRESHOLD = "overshoot_tier2_threshold"
CONF_OVERSHOOT_TIER3_THRESHOLD = "overshoot_tier3_threshold"

# Fan speed smoothing
CONF_ENABLE_FAN_SMOOTHING = "enable_fan_smoothing"
CONF_SMOOTHING_FACTOR = "smoothing_factor"
CONF_SMOOTHING_THRESHOLD = "smoothing_threshold"

# Adaptive learning
CONF_ENABLE_LEARNING = "enable_learning"
CONF_LEARNING_MODE = "learning_mode"
CONF_LEARNING_CONFIDENCE_THRESHOLD = "learning_confidence_threshold"
CONF_LEARNING_MAX_ADJUSTMENT = "learning_max_adjustment"

# Smart learning improvements
CONF_ENABLE_ADAPTIVE_BANDS = "enable_adaptive_bands"
CONF_ENABLE_ADAPTIVE_EFFICIENCY = "enable_adaptive_efficiency"
CONF_ENABLE_ADAPTIVE_PREDICTIVE = "enable_adaptive_predictive"
CONF_ENABLE_ADAPTIVE_AC_SETPOINT = "enable_adaptive_ac_setpoint"

# Adaptive balancing
CONF_ENABLE_ADAPTIVE_BALANCING = "enable_adaptive_balancing"
CONF_ENABLE_ROOM_COUPLING_DETECTION = "enable_room_coupling_detection"

# HVAC Modes
HVAC_MODE_COOL = "cool"
HVAC_MODE_HEAT = "heat"
HVAC_MODE_AUTO = "auto"
HVAC_MODE_DRY = "dry"
HVAC_MODE_FAN_ONLY = "fan_only"

# Default values
DEFAULT_TARGET_TEMPERATURE = 22
DEFAULT_UPDATE_INTERVAL = 0.5  # minutes - optimization interval (30 seconds)
DEFAULT_DATA_POLL_INTERVAL = 30  # seconds - how often to poll sensor data
DEFAULT_TEMPERATURE_DEADBAND = 0.5  # degrees C
DEFAULT_HVAC_MODE = HVAC_MODE_COOL
DEFAULT_AUTO_CONTROL_MAIN_AC = False
DEFAULT_AUTO_CONTROL_AC_TEMPERATURE = False
DEFAULT_ENABLE_NOTIFICATIONS = True
DEFAULT_STARTUP_DELAY = 120  # seconds (2 minutes) - prevents notifications during boot
DEFAULT_AC_TURN_ON_THRESHOLD = 1.0  # degrees C above target to turn AC on
DEFAULT_AC_TURN_OFF_THRESHOLD = 2.0  # degrees C below target to turn AC off
DEFAULT_ENABLE_WEATHER_ADJUSTMENT = False
DEFAULT_ENABLE_SCHEDULING = False

# Humidity control defaults
DEFAULT_ENABLE_HUMIDITY_CONTROL = False  # Disabled by default (opt-in)
DEFAULT_TARGET_HUMIDITY = 60  # Target relative humidity %
DEFAULT_HUMIDITY_DEADBAND = 5  # Acceptable range (±) from target before action
DEFAULT_DRY_MODE_HUMIDITY_THRESHOLD = 65  # Humidity % threshold to activate dry mode

# Weather adjustment parameters
WEATHER_TEMP_INFLUENCE = 0.5  # How much outdoor temp influences AC setpoint (0.0-1.0)
WEATHER_FORECAST_HOURS = 2  # How many hours ahead to consider

# Advanced settings defaults
DEFAULT_MAIN_FAN_HIGH_THRESHOLD = 2.5  # degrees C above target for HIGH fan speed
DEFAULT_MAIN_FAN_MEDIUM_THRESHOLD = 1.0  # degrees C above target for MEDIUM fan speed
DEFAULT_WEATHER_INFLUENCE_FACTOR = 0.5  # How much outdoor temp influences target (0.0-1.0)
DEFAULT_OVERSHOOT_TIER1_THRESHOLD = 1.0  # degrees C overshoot for tier 1 (25-35%)
DEFAULT_OVERSHOOT_TIER2_THRESHOLD = 2.0  # degrees C overshoot for tier 2 (15-25%)
DEFAULT_OVERSHOOT_TIER3_THRESHOLD = 3.0  # degrees C overshoot for tier 3 (0-5%)

# Fan speed smoothing defaults
DEFAULT_ENABLE_FAN_SMOOTHING = True  # Enable smoothing by default
DEFAULT_SMOOTHING_FACTOR = 0.7  # Weighting for new speed (0.0-1.0, 0.7 = 70% new, 30% old)
DEFAULT_SMOOTHING_THRESHOLD = 10  # Only smooth changes smaller than this (percentage points)

# Adaptive learning defaults
DEFAULT_ENABLE_LEARNING = False  # Disabled by default (opt-in feature)
DEFAULT_LEARNING_MODE = "passive"  # passive (collect only) or active (apply adjustments)
DEFAULT_LEARNING_CONFIDENCE_THRESHOLD = 0.7  # Minimum confidence to apply learning (0.0-1.0)
DEFAULT_LEARNING_MAX_ADJUSTMENT = 0.10  # Maximum parameter adjustment per update (10%)

# Smart learning improvement defaults
DEFAULT_ENABLE_ADAPTIVE_BANDS = True  # Apply learned thermal mass to temperature bands
DEFAULT_ENABLE_ADAPTIVE_EFFICIENCY = True  # Apply learned efficiency to fan speeds
DEFAULT_ENABLE_ADAPTIVE_PREDICTIVE = True  # Apply learned convergence to predictive control
DEFAULT_ENABLE_ADAPTIVE_AC_SETPOINT = False  # Conservative default - requires tuning

# Adaptive balancing defaults
DEFAULT_ENABLE_ADAPTIVE_BALANCING = True  # Apply learned biases to balancing
DEFAULT_ENABLE_ROOM_COUPLING_DETECTION = True  # Detect and use thermal coupling

# Inter-room balancing configuration
CONF_ENABLE_ROOM_BALANCING = "enable_room_balancing"
CONF_TARGET_ROOM_VARIANCE = "target_room_variance"
CONF_BALANCING_AGGRESSIVENESS = "balancing_aggressiveness"
CONF_MIN_AIRFLOW_PERCENT = "min_airflow_percent"

# Balancing defaults
DEFAULT_ENABLE_ROOM_BALANCING = True  # Enabled by default for better whole-house comfort
DEFAULT_TARGET_ROOM_VARIANCE = 1.5  # Target maximum temperature variance between rooms (°C)
DEFAULT_BALANCING_AGGRESSIVENESS = 0.2  # How aggressively to balance (0.0-0.5, higher = more aggressive)
DEFAULT_MIN_AIRFLOW_PERCENT = 15  # Minimum airflow to any room (%), ensures circulation

# HVAC mode change hysteresis (prevents rapid mode switching)
CONF_MODE_CHANGE_HYSTERESIS_TIME = "mode_change_hysteresis_time"
CONF_MODE_CHANGE_HYSTERESIS_TEMP = "mode_change_hysteresis_temp"
DEFAULT_MODE_CHANGE_HYSTERESIS_TIME = 300  # seconds (5 minutes) - minimum time between mode changes
DEFAULT_MODE_CHANGE_HYSTERESIS_TEMP = 0.3  # degrees C - extra deviation required to override hysteresis

# Occupancy-based control
CONF_ENABLE_OCCUPANCY_CONTROL = "enable_occupancy_control"
CONF_OCCUPANCY_SENSORS = "occupancy_sensors"  # Dict mapping room_name -> occupancy sensor entity
CONF_VACANT_ROOM_SETBACK = "vacant_room_setback"
CONF_VACANCY_TIMEOUT = "vacancy_timeout"
DEFAULT_ENABLE_OCCUPANCY_CONTROL = False  # Disabled by default (opt-in)
DEFAULT_VACANT_ROOM_SETBACK = 2.0  # degrees C to add/subtract from target for vacant rooms
DEFAULT_VACANCY_TIMEOUT = 300  # seconds (5 minutes) - time before considering room vacant

# Rate-of-change / predictive control
CONF_ENABLE_PREDICTIVE_CONTROL = "enable_predictive_control"
CONF_PREDICTIVE_LOOKAHEAD_MINUTES = "predictive_lookahead_minutes"
CONF_PREDICTIVE_BOOST_FACTOR = "predictive_boost_factor"
DEFAULT_ENABLE_PREDICTIVE_CONTROL = False  # Opt-in feature
DEFAULT_PREDICTIVE_LOOKAHEAD_MINUTES = 5.0  # Minutes to project temperature ahead
DEFAULT_PREDICTIVE_BOOST_FACTOR = 0.3  # How much to boost/reduce fan speed based on prediction (0.0-1.0)

# Compressor protection
CONF_ENABLE_COMPRESSOR_PROTECTION = "enable_compressor_protection"
CONF_COMPRESSOR_MIN_ON_TIME = "compressor_min_on_time"
CONF_COMPRESSOR_MIN_OFF_TIME = "compressor_min_off_time"
DEFAULT_ENABLE_COMPRESSOR_PROTECTION = True  # Enabled by default to protect hardware
DEFAULT_COMPRESSOR_MIN_ON_TIME = 180  # seconds (3 minutes) - minimum time AC stays on
DEFAULT_COMPRESSOR_MIN_OFF_TIME = 180  # seconds (3 minutes) - minimum time AC stays off

# Critical room protection
CONF_CRITICAL_ROOMS = "critical_rooms"  # Dict mapping room_name -> critical config
CONF_CRITICAL_TEMP_MAX = "critical_temp_max"
CONF_CRITICAL_TEMP_SAFE = "critical_temp_safe"
CONF_CRITICAL_WARNING_OFFSET = "critical_warning_offset"
CONF_CRITICAL_NOTIFY_SERVICES = "critical_notify_services"
DEFAULT_CRITICAL_WARNING_OFFSET = 2.0  # degrees C before critical to warn

# Critical room status values
CRITICAL_STATUS_NORMAL = "normal"
CRITICAL_STATUS_WARNING = "warning"
CRITICAL_STATUS_CRITICAL = "critical"
CRITICAL_STATUS_RECOVERING = "recovering"

# Days of week for scheduling
# Configurable notification services for optimizer alerts
CONF_NOTIFY_SERVICES = "notify_services"  # List of notification service targets
DEFAULT_NOTIFY_SERVICES = []  # Empty = persistent_notification only (default behavior)

SCHEDULE_DAYS_OPTIONS = [
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
    "weekdays",
    "weekends",
    "all"
]
