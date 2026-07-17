"""Diagnostics support for Normify."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .sensor import NormifySensor


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return configuration and live pipeline diagnostics."""
    diagnostics: dict[str, Any] = {
        "entry": {
            "title": entry.title,
            "unique_id": entry.unique_id,
            "version": entry.version,
            "minor_version": entry.minor_version,
            "data": dict(entry.data),
        }
    }

    sensor = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if isinstance(sensor, NormifySensor):
        diagnostics["pipeline"] = asdict(sensor.pipeline.snapshot())

    return diagnostics
