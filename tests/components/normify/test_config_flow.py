"""Tests for the Normify config flow."""

from homeassistant import config_entries
from homeassistant.const import CONF_NAME, CONF_SOURCE
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.normify.const import (
    CONF_ALPHA,
    CONF_DATA_POINTS,
    CONF_DATA_POINTS_TEXT,
    CONF_DEGREE,
    CONF_HIDE_SOURCE,
    CONF_MAXIMUM,
    CONF_MAXIMUM_INTERVAL,
    CONF_METHOD,
    CONF_MINIMUM,
    CONF_MINIMUM_INTERVAL,
    CONF_OFFSET,
    CONF_PRECISION,
    CONF_SCALE,
    CONF_STALE_AFTER,
    CONF_WINDOW,
    DOMAIN,
    SMOOTHING_MEDIAN,
)


async def _basic_step(hass: HomeAssistant, name: str = "") -> dict:
    hass.states.async_set(
        "sensor.garage_humidity_raw",
        "50",
        {"friendly_name": "Garage Humidity Raw", "unit_of_measurement": "%"},
    )
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    return await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_NAME: name,
            CONF_SOURCE: "sensor.garage_humidity_raw",
            "attribute": "",
            CONF_HIDE_SOURCE: False,
        },
    )


async def test_user_flow(hass: HomeAssistant) -> None:
    """Create a concise Normify pipeline through the guided UI."""
    result = await _basic_step(hass)
    assert result["step_id"] == "conditioning"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_MINIMUM: 0,
            CONF_MAXIMUM: 100,
            CONF_DATA_POINTS_TEXT: "38.68, 32\n79.89, 75",
            CONF_DEGREE: 1,
            CONF_SCALE: 1,
            CONF_OFFSET: 0,
            CONF_METHOD: SMOOTHING_MEDIAN,
            CONF_WINDOW: 3,
            CONF_ALPHA: 0.25,
        },
    )
    assert result["step_id"] == "publication"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_PRECISION: 2,
            CONF_MINIMUM_INTERVAL: {"seconds": 0},
            CONF_MAXIMUM_INTERVAL: {"minutes": 5},
            CONF_STALE_AFTER: {"minutes": 15},
        },
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Garage Humidity"
    assert result["data"][CONF_DATA_POINTS] == [[38.68, 32.0], [79.89, 75.0]]
    assert result["data"][CONF_MAXIMUM_INTERVAL] == 300
    assert result["data"][CONF_STALE_AFTER] == 900


async def test_invalid_calibration(hass: HomeAssistant) -> None:
    """Reject a degree that cannot be supported by the points."""
    result = await _basic_step(hass, "Bad calibration")
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_DATA_POINTS_TEXT: "0, 0\n1, 1",
            CONF_DEGREE: 2,
            CONF_SCALE: 1,
            CONF_OFFSET: 0,
            CONF_METHOD: "none",
            CONF_WINDOW: 3,
            CONF_ALPHA: 0.25,
        },
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "conditioning"
    assert result["errors"] == {"base": "invalid_configuration"}
