# Normify

Normify converts a raw Home Assistant sensor value into one dependable canonical
sensor without requiring a chain of Template, Compensation, Filter, and throttle
helpers.

Normify is the successor to `ha-calibration` and retains its polynomial
calibration lineage from Home Assistant Core's Compensation integration.

## Deliberately simple pipeline

```text
Source state or attribute
  → reject unknown, unavailable, missing, nonnumeric, NaN, and infinite values
  → clamp to an optional physical range
  → optional polynomial calibration, scale, and offset
  → optional single smoothing method
  → precision, minimum-change deadband, and time throttling
  → canonical Home Assistant sensor
```

Normify inherits the source unit, device class, state class, and icon whenever
Home Assistant exposes them. Overrides remain available for unusual sources, but
normal sensor configurations should not repeat metadata.

## YAML example

```yaml
normify:
  guest_bathroom_humidity:
    source: sensor.guest_bathroom_humidity_raw
    hide_source: true

    clamp:
      minimum: 0
      maximum: 100

    calibration:
      data_points:
        - [38.68, 32.0]
        - [79.89, 75.0]
      degree: 1

    smoothing:
      method: median
      window: 3

    publish:
      minimum_change: 0.2
      minimum_interval: 10
      maximum_interval: 300

    precision: 1
    stale_after: 900
```

Time values in YAML are seconds. The UI uses Home Assistant duration selectors.

## Behavior

- `unknown`, `unavailable`, missing attributes, nonnumeric values, `NaN`, and
  infinity are automatically ignored.
- Invalid samples never enter calibration or smoothing history.
- `clamp.minimum` and `clamp.maximum` constrain the raw numeric value rather
  than rejecting it.
- Only one smoothing method can be active: `median`, `moving_average`, or
  `exponential`.
- `minimum_change` suppresses insignificant canonical updates.
- `minimum_interval` limits publication frequency.
- `maximum_interval` releases the newest held value after the configured time.
- `stale_after` marks the canonical entity unavailable after no valid numeric
  source sample for the configured time.

## Metadata inheritance

For source-state conditioning, Normify inherits when available:

- Unit of measurement
- Device class
- State class
- Icon

The UI also derives the output name from the source friendly name and removes a
trailing `Raw`, `Unfiltered`, `Uncalibrated`, or `Source` suffix. A name override
is optional.

## Backward compatibility

Existing flat calibration-only YAML and existing v0.3 config entries continue to
load. New configurations should use the concise nested form above.

## Installation

Install as a custom HACS repository or copy `custom_components/normify` into the
Home Assistant configuration directory, restart Home Assistant, and add
**Normify** from **Settings → Devices & services → Add integration**.

## Development

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements-test.txt
ruff check .
ruff format --check .
mypy custom_components/normify
pytest --cov
```
