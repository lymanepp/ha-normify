"""Constants for the Normify integration."""

from homeassistant.const import Platform

DOMAIN = "normify"
PLATFORMS = [Platform.SENSOR]

CONF_DATA_POINTS = "data_points"
CONF_DATA_POINTS_TEXT = "data_points_text"
CONF_DEGREE = "degree"
CONF_HIDE_SOURCE = "hide_source"
CONF_PRECISION = "precision"
CONF_REJECT_VALUES = "reject_values"
CONF_REJECT_VALUES_TEXT = "reject_values_text"
CONF_MINIMUM = "minimum"
CONF_MAXIMUM = "maximum"
CONF_RANGE_ACTION = "range_action"
CONF_MAXIMUM_CHANGE = "maximum_change"
CONF_MAXIMUM_CHANGE_PER_SECOND = "maximum_change_per_second"
CONF_OUTLIER_WINDOW = "outlier_window"
CONF_OUTLIER_RADIUS = "outlier_radius"
CONF_OUTLIER_ACTION = "outlier_action"
CONF_SCALE = "scale"
CONF_OFFSET = "offset"
CONF_MEDIAN_WINDOW = "median_window"
CONF_MOVING_AVERAGE_WINDOW = "moving_average_window"
CONF_EXPONENTIAL_ALPHA = "exponential_alpha"
CONF_MINIMUM_CHANGE = "minimum_change"
CONF_MINIMUM_CHANGE_PERCENT = "minimum_change_percent"
CONF_MINIMUM_INTERVAL = "minimum_interval"
CONF_MAXIMUM_INTERVAL = "maximum_interval"
CONF_SAMPLE_THROTTLE = "sample_throttle"
CONF_STALE_AFTER = "stale_after"

CONF_CLAMP = "clamp"
CONF_CALIBRATION = "calibration"
CONF_SMOOTHING = "smoothing"
CONF_PUBLISH = "publish"
CONF_METHOD = "method"
CONF_WINDOW = "window"
CONF_ALPHA = "alpha"

SMOOTHING_NONE = "none"
SMOOTHING_MEDIAN = "median"
SMOOTHING_MOVING_AVERAGE = "moving_average"
SMOOTHING_EXPONENTIAL = "exponential"

RANGE_ACTION_REJECT = "reject"
RANGE_ACTION_CLAMP = "clamp"
OUTLIER_ACTION_REJECT = "reject"
OUTLIER_ACTION_MEDIAN = "median"

ATTR_ACCEPTED_SAMPLES = "accepted_samples"
ATTR_COEFFICIENTS = "coefficients"
ATTR_CONDITIONED_VALUE = "conditioned_value"
ATTR_HELD_SAMPLES = "held_samples"
ATTR_LAST_REJECTION = "last_rejection"
ATTR_PUBLISHED_SAMPLES = "published_samples"
ATTR_REJECTED_SAMPLES = "rejected_samples"
ATTR_SOURCE = "source"
ATTR_SOURCE_ATTRIBUTE = "source_attribute"
ATTR_SOURCE_VALUE = "source_value"

DEFAULT_DEGREE = 1
DEFAULT_PRECISION = 2
DEFAULT_RANGE_ACTION = RANGE_ACTION_REJECT
DEFAULT_OUTLIER_ACTION = OUTLIER_ACTION_REJECT
DEFAULT_SCALE = 1.0
DEFAULT_OFFSET = 0.0
DEFAULT_MEDIAN_WINDOW = 1
DEFAULT_MOVING_AVERAGE_WINDOW = 1
DEFAULT_SAMPLE_THROTTLE = 1
MAX_DEGREE = 7
MAX_WINDOW_SIZE = 1000
