"""Sensor platform for Signal Conditioner."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import cast

from homeassistant.components.sensor import (
    ATTR_STATE_CLASS,
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    ATTR_DEVICE_CLASS,
    ATTR_ICON,
    ATTR_UNIT_OF_MEASUREMENT,
    CONF_ATTRIBUTE,
    CONF_DEVICE_CLASS,
    CONF_ICON,
    CONF_NAME,
    CONF_SOURCE,
    CONF_UNIT_OF_MEASUREMENT,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
)
from homeassistant.core import (
    Event,
    EventStateChangedData,
    HomeAssistant,
    State,
    callback,
)
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.entity_registry import RegistryEntryHider
from homeassistant.helpers.event import (
    async_track_state_change_event,
    async_track_time_interval,
)

from .config import pipeline_config_from_data
from .const import CONF_HIDE_SOURCE, CONF_STATE_CLASS
from .pipeline import ConditioningPipeline, Disposition

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up a Signal Conditioner sensor from a config entry."""
    async_add_entities([SignalConditionerSensor(hass, entry)])


class SignalConditionerSensor(SensorEntity):
    """One sensor backed by a small in-memory conditioning pipeline."""

    _attr_should_poll = False

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the sensor."""
        config = entry.data
        self._source_entity_id = config[CONF_SOURCE]
        self._source_attribute = config.get(CONF_ATTRIBUTE)
        self._pipeline = ConditioningPipeline(pipeline_config_from_data(config))

        self._attr_unique_id = f"signal_conditioner.{entry.unique_id or entry.entry_id}"
        self._attr_name = config[CONF_NAME]
        self._attr_native_unit_of_measurement = config.get(CONF_UNIT_OF_MEASUREMENT)
        self._attr_device_class = cast(
            SensorDeviceClass | None, config.get(CONF_DEVICE_CLASS)
        )
        self._attr_state_class = cast(
            SensorStateClass | None, config.get(CONF_STATE_CLASS)
        )
        self._attr_icon = config.get(CONF_ICON)
        self._attr_available = False

        if config.get(CONF_HIDE_SOURCE):
            registry = er.async_get(hass)
            source_entry = registry.async_get(self._source_entity_id)
            if source_entry is not None and source_entry.hidden_by is None:
                registry.async_update_entity(
                    self._source_entity_id,
                    hidden_by=RegistryEntryHider.INTEGRATION,
                )

    async def async_added_to_hass(self) -> None:
        """Prime the sensor, subscribe to the source, and start its interval."""
        if (state := self.hass.states.get(self._source_entity_id)) is not None:
            self._process_source_state(state, write_state=False)

        self.async_on_remove(
            async_track_state_change_event(
                self.hass,
                [self._source_entity_id],
                self._async_source_state_listener,
            )
        )
        if self._pipeline.config.window_duration > 0:
            cancel_interval = async_track_time_interval(
                self.hass,
                self._async_interval,
                timedelta(seconds=self._pipeline.config.window_duration),
            )
            self.async_on_remove(cancel_interval)

    @callback
    def _async_source_state_listener(self, event: Event[EventStateChangedData]) -> None:
        """Handle source entity state changes."""
        new_state = event.data["new_state"]
        if new_state is None:
            self._handle_source_unavailable()
            return
        self._process_source_state(new_state)

    @callback
    def _process_source_state(self, state: State, *, write_state: bool = True) -> None:
        """Extract and condition one source state."""
        if state.state in (STATE_UNKNOWN, STATE_UNAVAILABLE):
            self._handle_source_unavailable(write_state=write_state)
            return

        if self._source_attribute:
            raw_value = state.attributes.get(self._source_attribute)
            if raw_value is None:
                self._handle_source_unavailable(write_state=write_state)
                return
        else:
            raw_value = state.state
            self._inherit_source_metadata(state)

        result = self._pipeline.process(raw_value)
        if result.disposition is Disposition.PUBLISH:
            self._publish(result.value, write_state=write_state)
        elif result.disposition is Disposition.REJECT:
            _LOGGER.debug(
                "Signal Conditioner rejected %s from %s: %s",
                raw_value,
                self._source_entity_id,
                result.reason,
            )

    @callback
    def _handle_source_unavailable(self, *, write_state: bool = True) -> None:
        """Remain unavailable only until the first value has been published."""
        if self._attr_native_value is not None or not self.available:
            return
        self._attr_available = False
        if write_state:
            self.async_write_ha_state()

    @callback
    def _async_interval(self, _now: datetime) -> None:
        """Publish once for a populated interval and nothing for an empty one."""
        result = self._pipeline.flush()
        if result.disposition is Disposition.PUBLISH:
            self._publish(result.value)

    @callback
    def _publish(self, value: float | None, *, write_state: bool = True) -> None:
        """Publish one conditioned value."""
        if value is None:
            return
        self._attr_native_value = value
        self._attr_available = True
        if write_state:
            self.async_write_ha_state()

    @callback
    def _inherit_source_metadata(self, state: State) -> None:
        """Inherit source metadata only when not explicitly configured."""
        if (
            self._attr_native_unit_of_measurement is None
            and (unit := state.attributes.get(ATTR_UNIT_OF_MEASUREMENT)) is not None
        ):
            self._attr_native_unit_of_measurement = unit
        if (
            self._attr_device_class is None
            and (device_class := state.attributes.get(ATTR_DEVICE_CLASS)) is not None
        ):
            self._attr_device_class = cast(SensorDeviceClass, device_class)
        if (
            self._attr_state_class is None
            and (state_class := state.attributes.get(ATTR_STATE_CLASS)) is not None
        ):
            self._attr_state_class = cast(SensorStateClass, state_class)
        if (
            self._attr_icon is None
            and (icon := state.attributes.get(ATTR_ICON)) is not None
        ):
            self._attr_icon = icon
