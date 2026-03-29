# EnOcean BLE Switches

Home Assistant custom integration for EnOcean BLE energy-harvesting switches, focused on PTM215B/PTM216B.

## Project Overview

This project provides a Home Assistant custom integration (`enocean_ble`) that passively listens for EnOcean BLE telegrams and exposes switch actions as Home Assistant events.

Current status:
- Repository and CI/test/tooling scaffold is in place.
- MVP implementation is in progress with AES-128 CCM MIC verification and passive BLE event decoding.

## Supported Hardware

- EnOcean PTM215B
- EnOcean PTM216B

## Quick Start Install

### HACS (recommended)
1. Open HACS in Home Assistant.
2. Add this repository as a custom repository (type: Integration).
3. Install `EnOcean BLE Switches`.
4. Restart Home Assistant.

### Manual custom repository install
1. Copy `custom_components/enocean_ble` into your Home Assistant `custom_components` directory.
2. Restart Home Assistant.
3. Add the integration from Settings > Devices & Services.

## Setup Methods

### NFC setup (PTM216B)
- Use the NFC onboarding flow from the integration config flow.
- Default PIN is `0000` (can be changed on device side).
- The integration extracts MAC address and security key during onboarding.
- Live validation checks that the device is currently visible via BLE scan.

### QR setup (PTM215B/PTM216B)
- Use the QR onboarding flow and paste the raw QR content.
- The integration parses MAC/security data automatically.
- Live validation checks that the device is currently visible via BLE scan.

## Event Model (MVP)

Event fired on Home Assistant bus:
- `enocean_ble_button_action`

Event attributes:
- `button`: `A0`, `A1`, `B0`, `B1`
- `event_type`: `press`, `release`, `long_press`, `long_release`
- `rssi`: BLE RSSI from advertisement
- `sequence_counter`: monotonically increasing telegram counter
- `mac_address`: source device MAC

## Factory Reset Procedure

Exact procedure:
- Dismount the switch from wall/plate.
- Hold `A0 + A1 + B0 + B1` while actuating the energy bow.
- Keep this combination for at least 10 seconds.

## Casambi Coexistence and Migration Notes

- Devices previously paired with Casambi should be factory reset before onboarding in Home Assistant.
- During migration, validate event reception in Home Assistant before removing old automations.
- Avoid running dual automations in both systems during transition.

## Local Development Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements_dev.txt
pre-commit install
```

Run checks:

```bash
ruff check .
mypy custom_components tests
pytest -q
```

## Troubleshooting

- No events received: verify BLE adapter availability and distance from switch.
- Intermittent reception: inspect RSSI and environmental interference.
- Onboarding fails: re-check NFC PIN/QR payload and perform factory reset if needed.
- Invalid security verification: ensure the correct per-device key is configured.

## Security Notes

- Security keys are stored in Home Assistant config entries and must never be logged in clear text.
- NFC default PIN `0000` should be treated as bootstrap-only and changed where supported.
- Diagnostic logs should redact cryptographic material.
- MIC verification uses AES-128 CCM as specified in PTM215B/PTM216B manuals.

## Roadmap

- BLE passive scan and telegram decoding for PTM215B/PTM216B.
- AES-128 MIC verification.
- Event entity mapping for A0/A1/B0/B1 with press/release/long variants.
- Device diagnostics and advanced troubleshooting tools.

## Contributing

1. Create a branch from `dev`.
2. Add/adjust tests for any behavior change.
3. Keep CI green (`ruff`, typing, `pytest`, HACS validation).
4. Open a PR to `dev`.

## CI Status

- CI workflow: lint, typing, tests.
- HACS validation workflow: custom integration structure checks.

## Specification References

- [PTM-215B User Manual](https://www.enocean.com/wp-content/uploads/downloads-produkte/en/products/enocean_modules_24ghz_ble/ptm-215b/user-manual-pdf/PTM-215B-User-Manual.pdf)
- [PTM-216B User Manual](https://www.enocean.com/wp-content/uploads/downloads-produkte/en/products/enocean_modules_24ghz_ble/ptm-216b/user-manual-pdf/PTM-216B-User-Manual-3.pdf)

## Project Documentation

- [Documentation index](docs/README.md)
