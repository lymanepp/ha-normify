"""Unit tests for the pure Normify conditioning pipeline."""

from datetime import UTC, datetime, timedelta

import pytest

from custom_components.normify.calibration import PolynomialCalibration
from custom_components.normify.pipeline import (
    ConditioningPipeline,
    Disposition,
    OutlierAction,
    PipelineConfig,
    RangeAction,
)

NOW = datetime(2026, 7, 16, 12, 0, tzinfo=UTC)


def test_rejects_sentinels_and_out_of_range_values() -> None:
    """Configured garbage and impossible values are rejected."""
    pipeline = ConditioningPipeline(
        PipelineConfig(reject_values=(-999.0,), minimum=0, maximum=100)
    )

    assert pipeline.process(-999, NOW).disposition is Disposition.REJECT
    assert pipeline.process(-1, NOW).reason == "below_minimum"
    assert pipeline.process(101, NOW).reason == "above_maximum"
    assert pipeline.stats.rejected == 3


def test_clamps_out_of_range_values() -> None:
    """Range policy can clamp rather than reject."""
    pipeline = ConditioningPipeline(
        PipelineConfig(minimum=0, maximum=100, range_action=RangeAction.CLAMP)
    )

    low = pipeline.process(-10, NOW)
    high = pipeline.process(110, NOW + timedelta(seconds=1))

    assert low.value == 0
    assert high.value == 100


def test_rejects_excessive_change_and_rate() -> None:
    """Absolute jump and rate-of-change gates use accepted raw samples."""
    jump = ConditioningPipeline(PipelineConfig(maximum_change=5))
    assert jump.process(10, NOW).disposition is Disposition.PUBLISH
    assert jump.process(16, NOW + timedelta(seconds=10)).reason == "maximum_change"

    rate = ConditioningPipeline(PipelineConfig(maximum_change_per_second=2))
    assert rate.process(10, NOW).disposition is Disposition.PUBLISH
    assert rate.process(15, NOW + timedelta(seconds=1)).reason == "maximum_rate"


def test_median_outlier_can_reject_or_substitute() -> None:
    """Median-band outlier handling supports both policies."""
    reject = ConditioningPipeline(PipelineConfig(outlier_window=3, outlier_radius=5))
    for index, value in enumerate((10, 11, 9)):
        reject.process(value, NOW + timedelta(seconds=index))
    assert reject.process(30, NOW + timedelta(seconds=4)).reason == "median_outlier"

    substitute = ConditioningPipeline(
        PipelineConfig(
            outlier_window=3,
            outlier_radius=5,
            outlier_action=OutlierAction.MEDIAN,
        )
    )
    for index, value in enumerate((10, 11, 9)):
        substitute.process(value, NOW + timedelta(seconds=index))
    result = substitute.process(30, NOW + timedelta(seconds=4))
    assert result.value == 10


def test_applies_calibration_scale_offset_and_rounding() -> None:
    """Correction stages run before final precision is applied."""
    calibration = PolynomialCalibration.fit([[0, 0], [10, 20]], degree=1, precision=12)
    pipeline = ConditioningPipeline(
        PipelineConfig(calibration=calibration, scale=0.5, offset=1, precision=2)
    )

    result = pipeline.process(3.333, NOW)

    assert result.value == 4.33


def test_smoothing_stages_run_in_order() -> None:
    """Median, moving average, and exponential filters compose predictably."""
    pipeline = ConditioningPipeline(
        PipelineConfig(
            median_window=3,
            moving_average_window=2,
            exponential_alpha=0.5,
            precision=3,
        )
    )

    assert pipeline.process(1, NOW).value == 1
    assert pipeline.process(3, NOW + timedelta(seconds=1)).value == 1.25
    assert pipeline.process(100, NOW + timedelta(seconds=2)).value == 1.875


def test_deadband_holds_until_maximum_interval() -> None:
    """A held value is forced out when maximum_interval expires."""
    pipeline = ConditioningPipeline(
        PipelineConfig(minimum_change=1, maximum_interval=10)
    )

    assert pipeline.process(10, NOW).disposition is Disposition.PUBLISH
    held = pipeline.process(10.2, NOW + timedelta(seconds=1))
    assert held.disposition is Disposition.HOLD
    assert held.next_wakeup == NOW + timedelta(seconds=10)
    assert pipeline.flush(NOW + timedelta(seconds=5)).disposition is Disposition.HOLD

    published = pipeline.flush(NOW + timedelta(seconds=10))
    assert published.disposition is Disposition.PUBLISH
    assert published.value == 10.2


def test_minimum_interval_and_sample_throttle() -> None:
    """Both gates must clear unless maximum_interval forces publication."""
    pipeline = ConditioningPipeline(
        PipelineConfig(minimum_interval=5, sample_throttle=2)
    )

    assert pipeline.process(1, NOW).disposition is Disposition.PUBLISH
    assert (
        pipeline.process(2, NOW + timedelta(seconds=1)).disposition is Disposition.HOLD
    )
    result = pipeline.process(3, NOW + timedelta(seconds=6))
    assert result.disposition is Disposition.PUBLISH
    assert result.value == 3


def test_absolute_or_percentage_deadband_can_publish() -> None:
    """Either configured deadband threshold permits publication."""
    pipeline = ConditioningPipeline(
        PipelineConfig(minimum_change=10, minimum_change_percent=5)
    )

    pipeline.process(100, NOW)
    assert (
        pipeline.process(104, NOW + timedelta(seconds=1)).disposition
        is Disposition.HOLD
    )
    assert (
        pipeline.process(106, NOW + timedelta(seconds=2)).disposition
        is Disposition.PUBLISH
    )


def test_stale_deadline_uses_last_accepted_sample() -> None:
    """Rejected samples do not postpone stale detection."""
    pipeline = ConditioningPipeline(PipelineConfig(maximum_change=2, stale_after=30))
    pipeline.process(10, NOW)
    pipeline.process(100, NOW + timedelta(seconds=20))

    assert pipeline.stale_deadline() == NOW + timedelta(seconds=30)
    assert not pipeline.is_stale(NOW + timedelta(seconds=29))
    assert pipeline.is_stale(NOW + timedelta(seconds=30))


@pytest.mark.parametrize("bad_value", ["garbage", "nan", "inf", None])
def test_rejects_nonfinite_source_values(bad_value: object) -> None:
    """Invalid source values never escape the pure pipeline."""
    pipeline = ConditioningPipeline(PipelineConfig())

    result = pipeline.process(bad_value, NOW)

    assert result.disposition is Disposition.REJECT
    assert result.reason is not None
