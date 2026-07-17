"""Pure measurement-conditioning pipeline used by Normify.

The module intentionally has no Home Assistant dependencies. It owns validation,
calibration, smoothing, publication policy, and diagnostics so the behavior can
be tested independently from entity lifecycle code.
"""

from __future__ import annotations

import math
import statistics
from collections import deque
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any, cast

from .calibration import (
    InvalidDataPointsError,
    InvalidSourceValueError,
    PolynomialCalibration,
)


class PipelineConfigurationError(ValueError):
    """Raised when a conditioning pipeline is internally inconsistent."""


class Disposition(StrEnum):
    """Outcome of processing or flushing a sample."""

    PUBLISH = "publish"
    HOLD = "hold"
    REJECT = "reject"


class RangeAction(StrEnum):
    """Action taken for a value outside the configured range."""

    REJECT = "reject"
    CLAMP = "clamp"


class OutlierAction(StrEnum):
    """Action taken for a median-band outlier."""

    REJECT = "reject"
    MEDIAN = "median"


@dataclass(frozen=True, slots=True)
class PipelineConfig:
    """Validated configuration for one conditioning pipeline."""

    calibration: PolynomialCalibration | None = None
    reject_values: tuple[float, ...] = ()
    minimum: float | None = None
    maximum: float | None = None
    range_action: RangeAction = RangeAction.REJECT
    maximum_change: float | None = None
    maximum_change_per_second: float | None = None
    outlier_window: int = 0
    outlier_radius: float | None = None
    outlier_action: OutlierAction = OutlierAction.REJECT
    scale: float = 1.0
    offset: float = 0.0
    median_window: int = 1
    moving_average_window: int = 1
    exponential_alpha: float | None = None
    precision: int = 2
    minimum_change: float | None = None
    minimum_change_percent: float | None = None
    minimum_interval: float = 0.0
    maximum_interval: float = 0.0
    sample_throttle: int = 1
    stale_after: float = 0.0

    def __post_init__(self) -> None:
        """Validate cross-field invariants."""
        finite_optional = {
            "minimum": self.minimum,
            "maximum": self.maximum,
            "maximum_change": self.maximum_change,
            "maximum_change_per_second": self.maximum_change_per_second,
            "outlier_radius": self.outlier_radius,
            "exponential_alpha": self.exponential_alpha,
            "minimum_change": self.minimum_change,
            "minimum_change_percent": self.minimum_change_percent,
        }
        for name, value in finite_optional.items():
            if value is not None and not math.isfinite(value):
                raise PipelineConfigurationError(f"{name} must be finite")

        for name, value in {
            "scale": self.scale,
            "offset": self.offset,
            "minimum_interval": self.minimum_interval,
            "maximum_interval": self.maximum_interval,
            "stale_after": self.stale_after,
        }.items():
            if not math.isfinite(value):
                raise PipelineConfigurationError(f"{name} must be finite")

        if self.minimum is not None and self.maximum is not None:
            if self.minimum > self.maximum:
                raise PipelineConfigurationError("minimum cannot exceed maximum")

        for name, value in {
            "maximum_change": self.maximum_change,
            "maximum_change_per_second": self.maximum_change_per_second,
            "outlier_radius": self.outlier_radius,
            "minimum_change": self.minimum_change,
            "minimum_change_percent": self.minimum_change_percent,
        }.items():
            if value is not None and value < 0:
                raise PipelineConfigurationError(f"{name} cannot be negative")

        if self.outlier_window < 0:
            raise PipelineConfigurationError("outlier_window cannot be negative")
        if (self.outlier_window > 0) != (self.outlier_radius is not None):
            raise PipelineConfigurationError(
                "outlier_window and outlier_radius must be configured together"
            )
        if self.outlier_window in (1, 2):
            raise PipelineConfigurationError("outlier_window must be 0 or at least 3")

        if self.median_window < 1:
            raise PipelineConfigurationError("median_window must be at least 1")
        if self.moving_average_window < 1:
            raise PipelineConfigurationError("moving_average_window must be at least 1")
        if self.exponential_alpha is not None and not (0 < self.exponential_alpha <= 1):
            raise PipelineConfigurationError(
                "exponential_alpha must be greater than 0 and at most 1"
            )
        if self.precision < 0:
            raise PipelineConfigurationError("precision cannot be negative")
        if self.minimum_interval < 0:
            raise PipelineConfigurationError("minimum_interval cannot be negative")
        if self.maximum_interval < 0:
            raise PipelineConfigurationError("maximum_interval cannot be negative")
        if self.maximum_interval > 0 and self.minimum_interval > self.maximum_interval:
            raise PipelineConfigurationError(
                "maximum_interval cannot be shorter than minimum_interval"
            )
        if self.sample_throttle < 1:
            raise PipelineConfigurationError("sample_throttle must be at least 1")
        if self.stale_after < 0:
            raise PipelineConfigurationError("stale_after cannot be negative")

        if not all(math.isfinite(value) for value in self.reject_values):
            raise PipelineConfigurationError("reject_values must be finite")


@dataclass(slots=True)
class PipelineStats:
    """Mutable counters for one pipeline."""

    received: int = 0
    accepted: int = 0
    rejected: int = 0
    held: int = 0
    published: int = 0
    rejection_reasons: dict[str, int] = field(default_factory=dict)

    def reject(self, reason: str) -> None:
        """Record one rejected sample."""
        self.rejected += 1
        self.rejection_reasons[reason] = self.rejection_reasons.get(reason, 0) + 1


@dataclass(frozen=True, slots=True)
class PipelineResult:
    """Result returned by process or flush."""

    disposition: Disposition
    value: float | None = None
    raw_value: float | None = None
    conditioned_value: float | None = None
    reason: str | None = None
    next_wakeup: datetime | None = None


@dataclass(frozen=True, slots=True)
class PipelineSnapshot:
    """Serializable runtime snapshot for diagnostics."""

    last_raw_value: float | None
    last_accepted_value: float | None
    last_conditioned_value: float | None
    last_published_value: float | None
    pending_value: float | None
    last_accepted_at: datetime | None
    last_published_at: datetime | None
    last_rejection_reason: str | None
    stats: Mapping[str, object]


class ConditioningPipeline:
    """Ordered raw-to-canonical measurement-conditioning pipeline."""

    def __init__(self, config: PipelineConfig) -> None:
        """Initialize the pipeline and all bounded histories."""
        self.config = config
        self.stats = PipelineStats()

        self._outlier_history: deque[float] = deque(
            maxlen=max(config.outlier_window, 1)
        )
        self._median_history: deque[float] = deque(maxlen=config.median_window)
        self._average_history: deque[float] = deque(maxlen=config.moving_average_window)
        self._exponential_value: float | None = None

        self._last_raw_value: float | None = None
        self._last_accepted_value: float | None = None
        self._last_conditioned_value: float | None = None
        self._last_published_value: float | None = None
        self._last_accepted_at: datetime | None = None
        self._last_published_at: datetime | None = None
        self._last_rejection_reason: str | None = None
        self._pending_value: float | None = None
        self._pending_raw_value: float | None = None
        self._samples_since_publish = 0

    @property
    def coefficients(self) -> tuple[float, ...]:
        """Return calibration coefficients, if polynomial calibration is enabled."""
        if self.config.calibration is None:
            return ()
        return self.config.calibration.coefficients

    @property
    def last_accepted_at(self) -> datetime | None:
        """Return the timestamp of the last accepted source sample."""
        return self._last_accepted_at

    @property
    def last_rejection_reason(self) -> str | None:
        """Return the most recent rejection reason."""
        return self._last_rejection_reason

    def process(self, source_value: object, timestamp: datetime) -> PipelineResult:
        """Process one source sample through every configured stage."""
        self.stats.received += 1

        try:
            raw_value = _finite_float(source_value)
        except InvalidSourceValueError as err:
            return self._reject("not_finite", reason_text=str(err))

        self._last_raw_value = raw_value

        if raw_value in self.config.reject_values:
            return self._reject("sentinel_value", raw_value=raw_value)

        accepted_value = raw_value
        if self.config.minimum is not None and accepted_value < self.config.minimum:
            if self.config.range_action is RangeAction.REJECT:
                return self._reject("below_minimum", raw_value=raw_value)
            accepted_value = self.config.minimum
        if self.config.maximum is not None and accepted_value > self.config.maximum:
            if self.config.range_action is RangeAction.REJECT:
                return self._reject("above_maximum", raw_value=raw_value)
            accepted_value = self.config.maximum

        if self._last_accepted_value is not None:
            change = abs(accepted_value - self._last_accepted_value)
            if (
                self.config.maximum_change is not None
                and change > self.config.maximum_change
            ):
                return self._reject("maximum_change", raw_value=raw_value)

            if (
                self.config.maximum_change_per_second is not None
                and self._last_accepted_at is not None
            ):
                elapsed = (timestamp - self._last_accepted_at).total_seconds()
                if elapsed <= 0:
                    if change > 0:
                        return self._reject(
                            "non_increasing_timestamp", raw_value=raw_value
                        )
                elif change / elapsed > self.config.maximum_change_per_second:
                    return self._reject("maximum_rate", raw_value=raw_value)

        if self.config.outlier_window > 0:
            if len(self._outlier_history) == self.config.outlier_window:
                center = float(statistics.median(self._outlier_history))
                radius = self.config.outlier_radius
                assert radius is not None
                if abs(accepted_value - center) > radius:
                    if self.config.outlier_action is OutlierAction.REJECT:
                        return self._reject("median_outlier", raw_value=raw_value)
                    accepted_value = center

        try:
            transformed_value = accepted_value
            if self.config.calibration is not None:
                transformed_value = self.config.calibration.evaluate(transformed_value)
            transformed_value = (
                transformed_value * self.config.scale + self.config.offset
            )
        except (InvalidSourceValueError, OverflowError):
            return self._reject("transformation_not_finite", raw_value=raw_value)
        if not math.isfinite(transformed_value):
            return self._reject("transformation_not_finite", raw_value=raw_value)

        median_input = transformed_value
        conditioned_value = median_input
        if self.config.median_window > 1:
            median_values = (
                *tuple(self._median_history)[-(self.config.median_window - 1) :],
                median_input,
            )
            conditioned_value = float(statistics.median(median_values))

        average_input = conditioned_value
        if self.config.moving_average_window > 1:
            average_values = (
                *tuple(self._average_history)[
                    -(self.config.moving_average_window - 1) :
                ],
                average_input,
            )
            conditioned_value = float(statistics.fmean(average_values))

        new_exponential_value = self._exponential_value
        if self.config.exponential_alpha is not None:
            if new_exponential_value is None:
                new_exponential_value = conditioned_value
            else:
                alpha = self.config.exponential_alpha
                new_exponential_value = (
                    alpha * conditioned_value + (1 - alpha) * new_exponential_value
                )
            conditioned_value = new_exponential_value

        conditioned_value = round(conditioned_value, self.config.precision)
        if not math.isfinite(conditioned_value):
            return self._reject("conditioned_not_finite", raw_value=raw_value)

        # Commit state only after the complete sample has successfully passed.
        if self.config.outlier_window > 0:
            self._outlier_history.append(accepted_value)
        if self.config.median_window > 1:
            self._median_history.append(median_input)
        if self.config.moving_average_window > 1:
            self._average_history.append(average_input)
        if self.config.exponential_alpha is not None:
            self._exponential_value = new_exponential_value

        self.stats.accepted += 1
        self._last_rejection_reason = None
        self._last_accepted_value = accepted_value
        self._last_accepted_at = timestamp
        self._last_conditioned_value = conditioned_value
        self._samples_since_publish += 1
        return self._publication_result(raw_value, conditioned_value, timestamp)

    def flush(self, timestamp: datetime) -> PipelineResult:
        """Publish a pending value when its time-based gates have elapsed."""
        if self._pending_value is None:
            return PipelineResult(Disposition.HOLD)

        force_due = self._maximum_interval_due(timestamp)
        meaningful = self._is_meaningful_change(self._pending_value)
        minimum_due = self._minimum_interval_due(timestamp)
        sample_due = self._samples_since_publish >= self.config.sample_throttle

        if force_due or (meaningful and minimum_due and sample_due):
            raw_value = self._pending_raw_value
            return self._publish(raw_value, self._pending_value, timestamp)

        return PipelineResult(
            Disposition.HOLD,
            raw_value=self._pending_raw_value,
            conditioned_value=self._pending_value,
            next_wakeup=self.next_wakeup(timestamp),
        )

    def next_wakeup(self, timestamp: datetime) -> datetime | None:
        """Return the next publication-policy deadline for a pending value."""
        if self._pending_value is None or self._last_published_at is None:
            return None

        deadlines: list[datetime] = []
        if self.config.maximum_interval > 0:
            deadlines.append(
                self._last_published_at
                + timedelta(seconds=self.config.maximum_interval)
            )

        if (
            self.config.minimum_interval > 0
            and self._is_meaningful_change(self._pending_value)
            and self._samples_since_publish >= self.config.sample_throttle
        ):
            deadlines.append(
                self._last_published_at
                + timedelta(seconds=self.config.minimum_interval)
            )

        future = [deadline for deadline in deadlines if deadline > timestamp]
        if future:
            return min(future)
        if deadlines:
            return timestamp
        return None

    def stale_deadline(self) -> datetime | None:
        """Return the timestamp when the output should become stale."""
        if self.config.stale_after <= 0 or self._last_accepted_at is None:
            return None
        return self._last_accepted_at + timedelta(seconds=self.config.stale_after)

    def is_stale(self, timestamp: datetime) -> bool:
        """Return whether no accepted sample has arrived within stale_after."""
        deadline = self.stale_deadline()
        return deadline is not None and timestamp >= deadline

    def snapshot(self) -> PipelineSnapshot:
        """Return a serializable diagnostic snapshot."""
        return PipelineSnapshot(
            last_raw_value=self._last_raw_value,
            last_accepted_value=self._last_accepted_value,
            last_conditioned_value=self._last_conditioned_value,
            last_published_value=self._last_published_value,
            pending_value=self._pending_value,
            last_accepted_at=self._last_accepted_at,
            last_published_at=self._last_published_at,
            last_rejection_reason=self._last_rejection_reason,
            stats={
                "received": self.stats.received,
                "accepted": self.stats.accepted,
                "rejected": self.stats.rejected,
                "held": self.stats.held,
                "published": self.stats.published,
                "rejection_reasons": dict(self.stats.rejection_reasons),
            },
        )

    def _publication_result(
        self, raw_value: float, conditioned_value: float, timestamp: datetime
    ) -> PipelineResult:
        """Apply deadband and throttle policy to an accepted value."""
        if self._last_published_value is None or self._last_published_at is None:
            return self._publish(raw_value, conditioned_value, timestamp)

        force_due = self._maximum_interval_due(timestamp)
        meaningful = self._is_meaningful_change(conditioned_value)
        minimum_due = self._minimum_interval_due(timestamp)
        sample_due = self._samples_since_publish >= self.config.sample_throttle

        if force_due or (meaningful and minimum_due and sample_due):
            return self._publish(raw_value, conditioned_value, timestamp)

        self.stats.held += 1
        self._pending_value = conditioned_value
        self._pending_raw_value = raw_value
        return PipelineResult(
            Disposition.HOLD,
            raw_value=raw_value,
            conditioned_value=conditioned_value,
            next_wakeup=self.next_wakeup(timestamp),
        )

    def _publish(
        self, raw_value: float | None, value: float, timestamp: datetime
    ) -> PipelineResult:
        """Record publication state and return a publish result."""
        self.stats.published += 1
        self._last_published_value = value
        self._last_published_at = timestamp
        self._pending_value = None
        self._pending_raw_value = None
        self._samples_since_publish = 0
        return PipelineResult(
            Disposition.PUBLISH,
            value=value,
            raw_value=raw_value,
            conditioned_value=value,
        )

    def _reject(
        self,
        reason: str,
        *,
        raw_value: float | None = None,
        reason_text: str | None = None,
    ) -> PipelineResult:
        """Record and return a rejected sample."""
        self.stats.reject(reason)
        self._last_rejection_reason = reason
        return PipelineResult(
            Disposition.REJECT,
            raw_value=raw_value,
            reason=reason_text or reason,
            next_wakeup=None,
        )

    def _is_meaningful_change(self, value: float) -> bool:
        """Return whether value clears at least one configured deadband."""
        if self._last_published_value is None:
            return True

        thresholds_configured = False
        threshold_results: list[bool] = []
        difference = abs(value - self._last_published_value)

        if self.config.minimum_change is not None:
            thresholds_configured = True
            threshold_results.append(difference >= self.config.minimum_change)

        if self.config.minimum_change_percent is not None:
            thresholds_configured = True
            if self._last_published_value == 0:
                percent = math.inf if difference > 0 else 0.0
            else:
                percent = difference / abs(self._last_published_value) * 100
            threshold_results.append(percent >= self.config.minimum_change_percent)

        return not thresholds_configured or any(threshold_results)

    def _minimum_interval_due(self, timestamp: datetime) -> bool:
        """Return whether the minimum publication interval has elapsed."""
        if self._last_published_at is None or self.config.minimum_interval <= 0:
            return True
        elapsed = (timestamp - self._last_published_at).total_seconds()
        return elapsed >= self.config.minimum_interval

    def _maximum_interval_due(self, timestamp: datetime) -> bool:
        """Return whether maximum_interval forces publication."""
        if self._last_published_at is None or self.config.maximum_interval <= 0:
            return False
        elapsed = (timestamp - self._last_published_at).total_seconds()
        return elapsed >= self.config.maximum_interval


def _finite_float(value: object) -> float:
    """Convert an arbitrary source value into a finite float."""
    try:
        result = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError) as err:
        raise InvalidSourceValueError("source value is not numeric") from err
    if not math.isfinite(result):
        raise InvalidSourceValueError("source value must be finite")
    return result


def parse_number_list(value: str | Iterable[object]) -> tuple[float, ...]:
    """Parse comma/newline-separated numbers or an iterable of values."""
    tokens: list[object]
    if isinstance(value, str):
        tokens = [
            token.strip()
            for line in value.splitlines()
            for token in line.split(",")
            if token.strip()
        ]
    else:
        tokens = list(value)

    numbers: list[float] = []
    for token in tokens:
        try:
            number = float(cast(Any, token))
        except (TypeError, ValueError) as err:
            raise PipelineConfigurationError(
                f"reject value {token!r} is not numeric"
            ) from err
        if not math.isfinite(number):
            raise PipelineConfigurationError("reject values must be finite")
        numbers.append(number)
    return tuple(numbers)


def build_pipeline_config(
    *,
    data_points: Iterable[Sequence[object]] = (),
    degree: int = 1,
    reject_values: Iterable[object] = (),
    minimum: float | None = None,
    maximum: float | None = None,
    range_action: str = RangeAction.REJECT,
    maximum_change: float | None = None,
    maximum_change_per_second: float | None = None,
    outlier_window: int = 0,
    outlier_radius: float | None = None,
    outlier_action: str = OutlierAction.REJECT,
    scale: float = 1.0,
    offset: float = 0.0,
    median_window: int = 1,
    moving_average_window: int = 1,
    exponential_alpha: float | None = None,
    precision: int = 2,
    minimum_change: float | None = None,
    minimum_change_percent: float | None = None,
    minimum_interval: float = 0.0,
    maximum_interval: float = 0.0,
    sample_throttle: int = 1,
    stale_after: float = 0.0,
) -> PipelineConfig:
    """Build and validate PipelineConfig from persisted primitive values."""
    points = tuple(tuple(pair) for pair in data_points)
    calibration: PolynomialCalibration | None = None
    if points:
        try:
            # Pipeline precision is applied after all transformations/filters.
            calibration = PolynomialCalibration.fit(
                points, degree=degree, precision=max(precision, 12)
            )
        except InvalidDataPointsError as err:
            raise PipelineConfigurationError(str(err)) from err

    try:
        normalized_range_action = RangeAction(range_action)
        normalized_outlier_action = OutlierAction(outlier_action)
    except ValueError as err:
        raise PipelineConfigurationError(str(err)) from err

    return PipelineConfig(
        calibration=calibration,
        reject_values=parse_number_list(reject_values),
        minimum=minimum,
        maximum=maximum,
        range_action=normalized_range_action,
        maximum_change=maximum_change,
        maximum_change_per_second=maximum_change_per_second,
        outlier_window=outlier_window,
        outlier_radius=outlier_radius,
        outlier_action=normalized_outlier_action,
        scale=scale,
        offset=offset,
        median_window=median_window,
        moving_average_window=moving_average_window,
        exponential_alpha=exponential_alpha,
        precision=precision,
        minimum_change=minimum_change,
        minimum_change_percent=minimum_change_percent,
        minimum_interval=minimum_interval,
        maximum_interval=maximum_interval,
        sample_throttle=sample_throttle,
        stale_after=stale_after,
    )
