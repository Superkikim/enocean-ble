# Config Flow

## Purpose

Commission one EnOcean BLE switch from Bluetooth discovery and create one config entry with:

- `mac_address`
- `security_key`

## Current Flow (Implemented)

`user` (Add integration) aborts with `discovery_required`: a switch is always added from its
Bluetooth discovery (press any button on it).

1. `bluetooth` (discovery)
- Starts from Bluetooth discovery.
- Stores discovered MAC/title, the discovery payload, and initializes trace state.

2. `bluetooth_method` (menu)
- `qr_scan`: scan the module label QR code with the camera.
- `qr_text`: type or paste the QR code text.
- `commissioning`: manual commissioning (button sequence), below.

### From the QR code

`qr_text` (form, field `qr_code`)
- Validates the text with `qr_onboarding.validate_qr_for_device()`, then creates the entry.

`qr_scan` (external step)
- Opens the scan page `/api/enocean_ble/qr_scan/<flow_id>` (`qr_scan.py`,
  `qr_scan_static/scan.html`). Needs an HTTPS URL; without one, falls back on `qr_text` with
  error `scan_https_required`.
- The page decodes the QR code with `BarcodeDetector`, else the embedded jsQR (Safari iOS), live
  or from a photo. On a computer it shows its own URL as a QR code (embedded qrcode-generator).
- The view (no auth, like an OAuth callback) only answers for an EnOcean BLE flow waiting on
  `qr_scan` (else 404). It validates the QR code and feeds it to the flow (`async_configure`)
  either way; on error it returns `400 {"code": …}`, shown on the phone with "go back to Home
  Assistant" (no rescan from the page).
- `qr_scan` then ends with `external_step_done` -> `qr_scan_done` (valid) or `qr_scan_error`.
- `qr_scan_done` (form): "QR code validated", Submit creates the entry.
- `qr_scan_error` (form): shows the error, Submit goes back to `bluetooth_method`.
- The phone app is in the background while the scan page is open (it opens in the browser) and
  may miss the one "flow progressed" event Home Assistant fires. The flow repeats it every 3 s
  (at most 2 min) until the frontend reloads the flow. A paused app can receive several at once,
  which is why both next steps are forms: reloading them has no effect, nothing is created
  before the user's Submit.

Validation (`validate_qr_for_device`), each failure has its own error code:
- `invalid_qr`: not a module label QR code (`30S<MAC>+Z<key>…`) nor free text with MAC + key.
- `qr_mac_mismatch`: the QR code address is not the discovered switch address.
- `qr_key_invalid`: the key verifies none of the telegrams received from the switch (AES-128 MIC
  check on data telegrams, key comparison on a commissioning telegram).
- `qr_no_telegram`: no telegram from the switch is known yet.

The scan page design is adapted from hass-pronote (delphiki/hass-pronote#229, MIT).

### Manual commissioning

3. `commissioning` (progress)
- Shows progress instructions to the user.
- Waits for a commissioning telegram (`len=26`) with a `120s` timeout.
- On success, parses and validates payload MAC and stores `security_key`.
- On timeout/invalid payload, returns a retry form on the same step.

4. `bluetooth_confirm` (explicit submit)
- Shows final confirmation once commissioning data is ready.
- User presses `Submit` to create the config entry.

## Important Behavior

- If a commissioning payload is already available for the active flow context, the flow can move to `bluetooth_confirm` immediately.
- `async_remove()` always logs flow removal and emits terminal trace if no entry was created.
- No business logic is done in frontend; state transitions are backend-driven.

## User-Facing Instruction Text

- Progress text comes from translation key `config.progress.waiting_commissioning`.
- Confirmation text comes from translation key `config.step.bluetooth_confirm.description`.
- Error texts are in `config.error.*`.
