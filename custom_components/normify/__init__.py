"""The Normify integration."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.components.sensor.const import (
    CONF_STATE_CLASS,
    DEVICE_CLASSES_SCHEMA,
    STATE_CLASSES_SCHEMA,
)
from homeassistant.config_entries import SOURCE_IMPORT, ConfigEntry
from homeassistant.const import (
    CONF_ATTRIBUTE,
    CONF_DEVICE_CLASS,
    CONF_NAME,
    CONF_SOURCE,
    CONF_UNIQUE_ID,
    CONF_UNIT_OF_MEASUREMENT,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType

from .config import flatten_configuration, pipeline_config_from_data
from .const import (
    CONF_ALPHA,
    CONF_CALIBRATION,
    CONF_CLAMP,
    CONF_DATA_POINTS,
    CONF_DEGREE,
    CONF_HIDE_SOURCE,
    CONF_MAXIMUM,
    CONF_MAXIMUM_INTERVAL,
    CONF_METHOD,
    CONF_MINIMUM,
    CONF_MINIMUM_CHANGE,
    CONF_MINIMUM_INTERVAL,
    CONF_OFFSET,
    CONF_PRECISION,
    CONF_PUBLISH,
    CONF_SCALE,
    CONF_SMOOTHING,
    CONF_STALE_AFTER,
    CONF_WINDOW,
    DEFAULT_DEGREE,
    DEFAULT_OFFSET,
    DEFAULT_PRECISION,
    DEFAULT_SCALE,
    DOMAIN,
    MAX_DEGREE,
    MAX_WINDOW_SIZE,
    PLATFORMS,
    SMOOTHING_EXPONENTIAL,
    SMOOTHING_MEDIAN,
    SMOOTHING_MOVING_AVERAGE,
)
from .pipeline import PipelineConfigurationError


def _validate_normify(value: dict[str, Any]) -> dict[str, Any]:
    """Validate and flatten one concise conditioning configuration."""
    if value.get(CONF_ATTRIBUTE) and value.get(CONF_HIDE_SOURCE):
        raise vol.Invalid("attribute and hide_source cannot be used together")
    flat = flatten_configuration(value)
    try:
        pipeline_config_from_data(flat)
    except PipelineConfigurationError as err:
        raise vol.Invalid(str(err)) from err
    return flat


_nonnegative_float = vol.All(vol.Coerce(float), vol.Range(min=0))
_positive_window = vol.All(vol.Coerce(int), vol.Range(min=1, max=MAX_WINDOW_SIZE))

CLAMP_SCHEMA = vol.Schema(
    {
        vol.Optional(CONF_MINIMUM): vol.Coerce(float),
        vol.Optional(CONF_MAXIMUM): vol.Coerce(float),
    }
)
CALIBRATION_SCHEMA = vol.Schema(
    {
        vol.Optional(CONF_DATA_POINTS, default=[]): [
            vol.ExactSequence([vol.Coerce(float), vol.Coerce(float)])
        ],
        vol.Optional(CONF_DEGREE, default=DEFAULT_DEGREE): vol.All(
            vol.Coerce(int), vol.Range(min=1, max=MAX_DEGREE)
        ),
        vol.Optional(CONF_SCALE, default=DEFAULT_SCALE): vol.Coerce(float),
        vol.Optional(CONF_OFFSET, default=DEFAULT_OFFSET): vol.Coerce(float),
    }
)
SMOOTHING_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_METHOD): vol.In(
            [SMOOTHING_MEDIAN, SMOOTHING_MOVING_AVERAGE, SMOOTHING_EXPONENTIAL]
        ),
        vol.Optional(CONF_WINDOW, default=3): _positive_window,
        vol.Optional(CONF_ALPHA, default=0.25): vol.All(
            vol.Coerce(float), vol.Range(min=0.01, max=1)
        ),
    }
)
PUBLISH_SCHEMA = vol.Schema(
    {
        vol.Optional(CONF_MINIMUM_CHANGE): _nonnegative_float,
        vol.Optional(CONF_MINIMUM_INTERVAL, default=0): _nonnegative_float,
        vol.Optional(CONF_MAXIMUM_INTERVAL, default=0): _nonnegative_float,
    }
)

NORMIFY_SCHEMA = vol.All(
    vol.Schema(
        {
            vol.Required(CONF_SOURCE): cv.entity_id,
            vol.Optional(CONF_ATTRIBUTE): cv.string,
            vol.Optional(CONF_HIDE_SOURCE, default=False): cv.boolean,
            vol.Optional(CONF_NAME): cv.string,
            vol.Optional(CONF_DEVICE_CLASS): DEVICE_CLASSES_SCHEMA,
            vol.Optional(CONF_UNIT_OF_MEASUREMENT): cv.string,
            vol.Optional(CONF_STATE_CLASS): STATE_CLASSES_SCHEMA,
            vol.Optional(CONF_CLAMP): CLAMP_SCHEMA,
            vol.Optional(CONF_CALIBRATION): CALIBRATION_SCHEMA,
            vol.Optional(CONF_SMOOTHING): SMOOTHING_SCHEMA,
            vol.Optional(CONF_PUBLISH): PUBLISH_SCHEMA,
            # Legacy flat keys remain accepted for existing installations.
            vol.Optional(CONF_MINIMUM): vol.Coerce(float),
            vol.Optional(CONF_MAXIMUM): vol.Coerce(float),
            vol.Optional(CONF_DATA_POINTS): [
                vol.ExactSequence([vol.Coerce(float), vol.Coerce(float)])
            ],
            vol.Optional(CONF_DEGREE): vol.All(
                vol.Coerce(int), vol.Range(min=1, max=MAX_DEGREE)
            ),
            vol.Optional(CONF_SCALE): vol.Coerce(float),
            vol.Optional(CONF_OFFSET): vol.Coerce(float),
            vol.Optional(CONF_PRECISION, default=DEFAULT_PRECISION): vol.All(
                vol.Coerce(int), vol.Range(min=0, max=12)
            ),
            vol.Optional(CONF_STALE_AFTER, default=0): _nonnegative_float,
        }
    ),
    _validate_normify,
)

CONFIG_SCHEMA = vol.Schema(
    {DOMAIN: vol.Schema({cv.slug: NORMIFY_SCHEMA})}, extra=vol.ALLOW_EXTRA
)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Import YAML definitions into config entries."""
    for object_id, raw_config in config.get(DOMAIN, {}).items():
        entry_data = dict(raw_config)
        entry_data[CONF_UNIQUE_ID] = object_id
        entry_data.setdefault(CONF_NAME, object_id.replace("_", " ").title())
        hass.async_create_task(
            hass.config_entries.flow.async_init(
                DOMAIN,
                context={"source": SOURCE_IMPORT},
                data=entry_data,
            )
        )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Normify from a config entry."""
    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a Normify config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Keep existing flat entries compatible with the simplified public schema."""
    if entry.version < 2:
        hass.config_entries.async_update_entry(entry, version=2, minor_version=2)
    return True


async def _async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload Normify when its config entry changes."""
    await hass.config_entries.async_reload(entry.entry_id)
