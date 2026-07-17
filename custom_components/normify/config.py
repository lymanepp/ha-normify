"""Configuration normalization shared by setup, flows, and entities."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast

from .const import (
    CONF_ALPHA,
    CONF_CALIBRATION,
    CONF_CLAMP,
    CONF_DATA_POINTS,
    CONF_DEGREE,
    CONF_EXPONENTIAL_ALPHA,
    CONF_MAXIMUM,
    CONF_MAXIMUM_CHANGE,
    CONF_MAXIMUM_CHANGE_PER_SECOND,
    CONF_MAXIMUM_INTERVAL,
    CONF_MEDIAN_WINDOW,
    CONF_METHOD,
    CONF_MINIMUM,
    CONF_MINIMUM_CHANGE,
    CONF_MINIMUM_INTERVAL,
    CONF_MOVING_AVERAGE_WINDOW,
    CONF_OFFSET,
    CONF_OUTLIER_ACTION,
    CONF_OUTLIER_RADIUS,
    CONF_OUTLIER_WINDOW,
    CONF_PRECISION,
    CONF_PUBLISH,
    CONF_RANGE_ACTION,
    CONF_REJECT_VALUES,
    CONF_SAMPLE_THROTTLE,
    CONF_SCALE,
    CONF_SMOOTHING,
    CONF_STALE_AFTER,
    CONF_WINDOW,
    DEFAULT_DEGREE,
    DEFAULT_OFFSET,
    DEFAULT_OUTLIER_ACTION,
    DEFAULT_PRECISION,
    DEFAULT_SAMPLE_THROTTLE,
    DEFAULT_SCALE,
    SMOOTHING_EXPONENTIAL,
    SMOOTHING_MEDIAN,
    SMOOTHING_MOVING_AVERAGE,
)
from .pipeline import PipelineConfig, RangeAction, build_pipeline_config


def flatten_configuration(data: Mapping[str, Any]) -> dict[str, Any]:
    """Flatten the concise public configuration into the internal pipeline schema."""
    flat = dict(data)

    clamp = flat.pop(CONF_CLAMP, None)
    if isinstance(clamp, Mapping):
        if CONF_MINIMUM in clamp:
            flat[CONF_MINIMUM] = clamp[CONF_MINIMUM]
        if CONF_MAXIMUM in clamp:
            flat[CONF_MAXIMUM] = clamp[CONF_MAXIMUM]
        flat["range_action"] = RangeAction.CLAMP.value

    calibration = flat.pop(CONF_CALIBRATION, None)
    if isinstance(calibration, Mapping):
        for key in (CONF_DATA_POINTS, CONF_DEGREE, CONF_SCALE, CONF_OFFSET):
            if key in calibration:
                flat[key] = calibration[key]

    smoothing = flat.pop(CONF_SMOOTHING, None)
    if isinstance(smoothing, Mapping):
        method = smoothing.get(CONF_METHOD)
        if method == SMOOTHING_MEDIAN:
            flat[CONF_MEDIAN_WINDOW] = smoothing.get(CONF_WINDOW, 3)
        elif method == SMOOTHING_MOVING_AVERAGE:
            flat[CONF_MOVING_AVERAGE_WINDOW] = smoothing.get(CONF_WINDOW, 3)
        elif method == SMOOTHING_EXPONENTIAL:
            flat[CONF_EXPONENTIAL_ALPHA] = smoothing.get(CONF_ALPHA, 0.25)

    publish = flat.pop(CONF_PUBLISH, None)
    if isinstance(publish, Mapping):
        for key in (CONF_MINIMUM_CHANGE, CONF_MINIMUM_INTERVAL, CONF_MAXIMUM_INTERVAL):
            if key in publish:
                flat[key] = publish[key]

    return flat


def pipeline_config_from_data(data: Mapping[str, Any]) -> PipelineConfig:
    """Build the pure pipeline configuration from persisted entry data."""
    data = flatten_configuration(data)
    return build_pipeline_config(
        data_points=data.get(CONF_DATA_POINTS, ()),
        degree=int(data.get(CONF_DEGREE, DEFAULT_DEGREE)),
        minimum=_optional_float(data, CONF_MINIMUM),
        maximum=_optional_float(data, CONF_MAXIMUM),
        reject_values=data.get(CONF_REJECT_VALUES, ()),
        range_action=str(data.get(CONF_RANGE_ACTION, RangeAction.CLAMP.value)),
        maximum_change=_optional_float(data, CONF_MAXIMUM_CHANGE),
        maximum_change_per_second=_optional_float(data, CONF_MAXIMUM_CHANGE_PER_SECOND),
        outlier_window=int(data.get(CONF_OUTLIER_WINDOW, 0)),
        outlier_radius=_optional_float(data, CONF_OUTLIER_RADIUS),
        outlier_action=str(data.get(CONF_OUTLIER_ACTION, DEFAULT_OUTLIER_ACTION)),
        scale=float(data.get(CONF_SCALE, DEFAULT_SCALE)),
        offset=float(data.get(CONF_OFFSET, DEFAULT_OFFSET)),
        median_window=int(data.get(CONF_MEDIAN_WINDOW, 1)),
        moving_average_window=int(data.get(CONF_MOVING_AVERAGE_WINDOW, 1)),
        exponential_alpha=_optional_float(data, CONF_EXPONENTIAL_ALPHA),
        precision=int(data.get(CONF_PRECISION, DEFAULT_PRECISION)),
        minimum_change=_optional_float(data, CONF_MINIMUM_CHANGE),
        minimum_change_percent=_optional_float(data, "minimum_change_percent"),
        minimum_interval=float(data.get(CONF_MINIMUM_INTERVAL, 0)),
        maximum_interval=float(data.get(CONF_MAXIMUM_INTERVAL, 0)),
        sample_throttle=int(data.get(CONF_SAMPLE_THROTTLE, DEFAULT_SAMPLE_THROTTLE)),
        stale_after=float(data.get(CONF_STALE_AFTER, 0)),
    )


def _optional_float(data: Mapping[str, Any], key: str) -> float | None:
    value = data.get(key)
    if value in (None, ""):
        return None
    return float(cast(Any, value))
