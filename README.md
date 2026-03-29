# EnOcean BLE (PTM215B/PTM216B) for Home Assistant

`enocean_ble` is a Home Assistant custom integration for EnOcean BLE
energy-harvesting switches (PTM215B/PTM216B).

It provides:
- Bluetooth discovery + guided commissioning flow
- Secure telegram parsing (MIC verification)
- Button events as native Home Assistant `event` entities

## Supported Devices

- EnOcean PTM215B
- EnOcean PTM216B

## Installation

### HACS (recommended)
1. HACS -> `Integrations` -> `...` -> `Custom repositories`
2. Add this repository URL, category: `Integration`
3. Install `EnOcean BLE`
4. Restart Home Assistant

### Manual
1. Copy [`custom_components/enocean_ble`](custom_components/enocean_ble) to your HA `custom_components` directory
2. Restart Home Assistant
3. Settings -> Devices & Services -> `Add Integration` -> `EnOcean BLE`

## Commissioning Flow

Current flow:
1. Click `Add` from Bluetooth discovery
2. Progress screen waits for commissioning telegram (`LEN=26`)
3. Confirm screen is shown
4. Submit creates the config entry

Notes:
- If the switch is already in commissioning mode, progress can complete almost immediately.
- After success, press another button to exit commissioning mode on the switch.

## Events

The integration creates 4 event entities (Button 1..4).

Event type values:
- `press`
- `release`
- `long_press`
- `long_release`

Event data includes:
- `mac_address`
- `rssi`
- `sequence_counter`

## Troubleshooting

- Device re-adds immediately after deletion:
  the switch is likely still in commissioning mode and keeps sending `LEN=26`.
- No button events:
  verify BLE reception and that commissioning completed successfully.
- Intermittent events:
  check distance/RSSI/interference.

To inspect debug logs:
1. Enable debug logging for `custom_components.enocean_ble`
2. Reproduce the issue
3. Review `FLOW_TRACE_V3` lines in Home Assistant logs

## Development

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements_dev.txt
```

Checks:

```bash
ruff check .
mypy custom_components tests
pytest -q
```

## Security

- Device security keys are stored in config entries.
- Keys must never be logged in clear text.
- Telegram authentication uses AES-128 CCM MIC verification.

## References

- [PTM-215B User Manual](https://www.enocean.com/wp-content/uploads/downloads-produkte/en/products/enocean_modules_24ghz_ble/ptm-215b/user-manual-pdf/PTM-215B-User-Manual.pdf)
- [PTM-216B User Manual](https://www.enocean.com/wp-content/uploads/downloads-produkte/en/products/enocean_modules_24ghz_ble/ptm-216b/user-manual-pdf/PTM-216B-User-Manual-3.pdf)
- [`docs/README.md`](docs/README.md)
