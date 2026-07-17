"""Tests for the Normify sensor entity."""

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    ATTR_DEVICE_CLASS,
    ATTR_UNIT_OF_MEASUREMENT,
    CONF_NAME,
    CONF_SOURCE,
    STATE_UNAVAILABLE,
)
from homeassistant.core import HomeAssistant

from custom_components.normify.const import (
    ATTR_SOURCE_VALUE,
    CONF_DATA_POINTS,
    CONF_DEGREE,
    CONF_HIDE_SOURCE,
    CONF_PRECISION,
    DOMAIN,
)


async def test_sensor_updates_and_inherits_metadata(hass: HomeAssistant) -> None:
    """Calibrate source values and inherit source metadata."""
    hass.states.async_set(
        "sensor.raw_temperature",
        "4",
        {
            ATTR_UNIT_OF_MEASUREMENT: "°C",
            ATTR_DEVICE_CLASS: "temperature",
            "state_class": "measurement",
        },
    )

    entry = ConfigEntry(
        version=1,
        minor_version=1,
        domain=DOMAIN,
        title="Corrected temperature",
        data={
            CONF_NAME: "Corrected temperature",
            CONF_SOURCE: "sensor.raw_temperature",
            CONF_DATA_POINTS: [[1.0, 2.0], [2.0, 3.0]],
            CONF_DEGREE: 1,
            CONF_PRECISION: 2,
            CONF_HIDE_SOURCE: False,
        },
        source="user",
        unique_id="corrected_temperature",
        discovery_keys={},
        options={},
        subentries_data=[],
    )
    hass.config_entries._entries[entry.entry_id] = entry

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    state = hass.states.get("sensor.corrected_temperature")
    assert state is not None
    assert float(state.state) == 5.0
    assert state.attributes[ATTR_UNIT_OF_MEASUREMENT] == "°C"
    assert state.attributes[ATTR_DEVICE_CLASS] == "temperature"
    assert state.attributes[ATTR_SOURCE_VALUE] == 4.0

    hass.states.async_set("sensor.raw_temperature", "7", {})
    await hass.async_block_till_done()

    state = hass.states.get("sensor.corrected_temperature")
    assert state is not None
    assert float(state.state) == 8.0
    assert state.attributes[ATTR_UNIT_OF_MEASUREMENT] == "°C"


async def test_unavailable_source_retains_last_valid_value(hass: HomeAssistant) -> None:
    """Preserve Calibration's established unavailable-state behavior."""
    hass.states.async_set("sensor.raw", "3")

    entry = ConfigEntry(
        version=1,
        minor_version=1,
        domain=DOMAIN,
        title="Stable value",
        data={
            CONF_NAME: "Stable value",
            CONF_SOURCE: "sensor.raw",
            CONF_DATA_POINTS: [[0.0, 0.0], [1.0, 1.0]],
            CONF_DEGREE: 1,
            CONF_PRECISION: 2,
            CONF_HIDE_SOURCE: False,
        },
        source="user",
        unique_id="stable_value",
        discovery_keys={},
        options={},
        subentries_data=[],
    )
    hass.config_entries._entries[entry.entry_id] = entry

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get("sensor.stable_value").state == "3.0"

    hass.states.async_set("sensor.raw", STATE_UNAVAILABLE)
    await hass.async_block_till_done()
    assert hass.states.get("sensor.stable_value").state == "3.0"


async def test_sensor_conditions_rejects_and_deadbands(hass: HomeAssistant) -> None:
    """The entity publishes only canonical values from the in-memory pipeline."""
    from custom_components.normify.const import (
        ATTR_REJECTED_SAMPLES,
        CONF_MINIMUM,
        CONF_MINIMUM_CHANGE,
        CONF_REJECT_VALUES,
    )

    hass.states.async_set("sensor.raw_conditioned", "10")
    entry = ConfigEntry(
        version=2,
        minor_version=1,
        domain=DOMAIN,
        title="Conditioned value",
        data={
            CONF_NAME: "Conditioned value",
            CONF_SOURCE: "sensor.raw_conditioned",
            CONF_DATA_POINTS: [],
            CONF_PRECISION: 2,
            CONF_HIDE_SOURCE: False,
            CONF_REJECT_VALUES: [-999],
            CONF_MINIMUM: 0,
            CONF_MINIMUM_CHANGE: 1,
        },
        source="user",
        unique_id="conditioned_value",
        discovery_keys={},
        options={},
        subentries_data=[],
    )
    hass.config_entries._entries[entry.entry_id] = entry

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get("sensor.conditioned_value").state == "10.0"

    hass.states.async_set("sensor.raw_conditioned", "10.2")
    await hass.async_block_till_done()
    assert hass.states.get("sensor.conditioned_value").state == "10.0"

    hass.states.async_set("sensor.raw_conditioned", "-999")
    await hass.async_block_till_done()
    assert hass.states.get("sensor.conditioned_value").state == "10.0"

    hass.states.async_set("sensor.raw_conditioned", "11.5")
    await hass.async_block_till_done()
    state = hass.states.get("sensor.conditioned_value")
    assert state.state == "11.5"
    assert state.attributes[ATTR_REJECTED_SAMPLES] == 1


async def test_sensor_becomes_unavailable_when_stale(hass: HomeAssistant) -> None:
    """The stale timer marks a retained canonical value unavailable."""
    from datetime import timedelta

    from pytest_homeassistant_custom_component.common import async_fire_time_changed

    from custom_components.normify.const import CONF_STALE_AFTER

    hass.states.async_set("sensor.raw_stale", "10")
    source_state = hass.states.get("sensor.raw_stale")
    assert source_state is not None

    entry = ConfigEntry(
        version=2,
        minor_version=1,
        domain=DOMAIN,
        title="Stale value",
        data={
            CONF_NAME: "Stale value",
            CONF_SOURCE: "sensor.raw_stale",
            CONF_DATA_POINTS: [],
            CONF_PRECISION: 2,
            CONF_HIDE_SOURCE: False,
            CONF_STALE_AFTER: 5,
        },
        source="user",
        unique_id="stale_value",
        discovery_keys={},
        options={},
        subentries_data=[],
    )
    hass.config_entries._entries[entry.entry_id] = entry

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get("sensor.stale_value").state == "10.0"

    async_fire_time_changed(hass, source_state.last_updated + timedelta(seconds=6))
    await hass.async_block_till_done()

    assert hass.states.get("sensor.stale_value").state == STATE_UNAVAILABLE
