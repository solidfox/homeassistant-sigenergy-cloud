# Sigenergy

Home Assistant custom integration for Sigenergy Cloud.

[![Open your Home Assistant instance and open this repository in HACS.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=solidfox&repository=homeassistant-sigenergy-cloud&category=integration)

The integration uses the published
[`sigenergy-cloud`](https://github.com/solidfox/sigenergy-cloud) Python package
for Sigenergy Cloud API access and exposes Sigenergy station,
battery, grid, PV, smart load, and DC charger controls in Home Assistant.

## Features

- Config flow with Sigenergy Cloud username, password, and region selection.
- Energy flow sensors for PV, grid, load, battery, battery SOC, and EV charging.
- Battery SOC, grid import/export, peak shaving, and operational mode controls.
- DC charger status, session, OCPP, alarm, charge-limit, V2X, and bidirectional
  controls when a Sigenergy DC charger is available on the account.

## Installation

### HACS

1. Use the button above to open this repository in HACS, or add it manually as a custom repository.
2. Select category `Integration` if adding it manually.
3. Download `Sigenergy` in HACS.
4. Restart Home Assistant.
5. Add the integration from **Settings > Devices & services > Add integration**.

### Manual

Copy `custom_components/sigenergy` into your Home Assistant
`custom_components` directory, restart Home Assistant, and add the integration
from **Settings > Devices & services**.

## Development

Install the development requirements and run the local checks:

```bash
python3 -m pip install -r requirements.txt
scripts/lint
```

The integration depends on the external `sigenergy-cloud` package pinned in
`custom_components/sigenergy/manifest.json`. Release the library package first,
then update the manifest pin when publishing integration changes that require a
new library version.
