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

## Compatibility

Tested with:
- Feller EDIZIOdue BLE Switch (user-tested in this project)

Verified PTM21x BLE products (manufacturer documentation):
- PTM 215B module (`S3221-A215`)
- PTM 216B module (`S3221-A216`)
- Easyfit Single / Double Rocker Wall Switch for BLE (`EWSSB / EWSDB`)
- Easyfit Single / Double Rocker Pad for BLE (`ESRPB / EDRPB`)

Regional fit:
- Europe (55x55 form factor): `EWSSB / EWSDB`
- US-style rocker pad format: `ESRPB / EDRPB`
- Switzerland: Feller EDIZIOdue BLE Switch (project-tested)

Compatibility assumption:
- In general, PTM215B/PTM216B-based BLE switches should work with this integration.
- However, compatibility is not mathematically guaranteed if product NFC/BLE settings were customized.

Important:
- Not every product labeled "EnOcean" is BLE.
- This integration targets BLE telegrams in the 2.4 GHz band from PTM215B/PTM216B family devices.
- Sub-GHz EnOcean products (e.g. 868/902 MHz) are out of scope for this integration.

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

## Migration / Factory Reset

If the switch has been used in another ecosystem (for example Casambi), commissioning in Home Assistant can fail if the active key/settings no longer match what you expect.

> [!WARNING]
> If auto-commissioning never starts (or never yields a commissioning telegram), the device may have radio commissioning disabled by prior NFC/OEM configuration.

In that case, perform a factory reset on the switch module:
1. Remove rocker and housing to access module contacts.
2. Press `A0 + A1 + B0 + B1` together.
3. While holding those contacts, press the energy bow.
4. Keep the energy bow pressed for at least 10 seconds.
5. Release and retry commissioning.

Practical tip:
- This is physically tricky. A common trick is to hold the 4 contacts with one hand (or a small non-conductive tool) and press/hold the energy bow with the other hand.
- Add a photo/diagram in your docs for contact positions, it helps a lot in real life.

> [!WARNING]
> Factory reset restores module defaults (including commissioning-related settings and security defaults).
> In some OEM deployments, this can require re-provisioning before the switch can be used again in the OEM ecosystem.
> For Casambi-like consumer setups this is often not blocking, but this cannot be guaranteed for every OEM workflow.

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

## Usage Examples

1. Single click on Button 1 (`press`) -> toggle a room light.
2. Long press on Button 1 (`long_press`) -> start dimming up.
3. Long release on Button 1 (`long_release`) -> stop dimming.
4. Button 2 -> activate "Away" scene.
5. Button 3 -> trigger "Movie" scene.
6. Button 4 -> all lights off.

## Troubleshooting

- Device re-adds immediately after deletion:
  the switch is likely still in commissioning mode and keeps sending `LEN=26`.
- No button events:
  verify BLE reception and that commissioning completed successfully.
- Auto-commissioning sequence never works:
  device may have commissioning mode disabled by prior configuration; try factory reset.
- Intermittent events:
  check distance/RSSI/interference.
- Occasional missed press:
  can happen on 2.4 GHz BLE in real environments (interference, attenuation, collisions). This is inherent to radio communication and not always a software defect.

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
