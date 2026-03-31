# Architecture

## Runtime Components

- `config_flow.py`
- Bluetooth discovery entrypoint, commissioning progress stage (`len=26`), explicit confirm, config entry creation.
- `__init__.py`
- Passive BLE callback registration, telegram parsing, event bus emission, dispatcher signal fan-out.
- `parser.py`
- Commissioning and runtime telegram parsing.
- `crypto.py`
- MIC/integrity validation utilities.
- `event.py`
- Four button event entities (`A0`, `A1`, `B0`, `B1`).
- `sensor.py`
- Four enum sensors mirroring the latest per-button event (`press`, `release`, `long_press`, `long_release`).
- `const.py`
- Domain constants, event names, protocol constants.

## Data Path

1. BLE advertisement is received by Home Assistant Bluetooth.
2. Integration filters by configured MAC and EnOcean manufacturer data.
3. Payload is parsed.
4. Integration fires bus events:
- `enocean_ble_button_event` (canonical)
- `enocean_ble_button_action` (legacy compatibility)
5. Integration dispatches internal signal per entry.
6. Event entities and sensor entities update from the same parsed payload.

## Commissioning Path

1. Discovery starts config flow.
2. Progress step waits for commissioning telegram (`len=26`, timeout `120s`).
3. Payload is validated and security key stored in flow state.
4. Confirm step waits for explicit `Submit`.
5. Entry is created with `mac_address` and `security_key`.

## Device Model in HA

Device registry metadata currently uses:

- `manufacturer = "EnOcean"`
- `model = "PTM 215B/PTM 216B"`

## Logging

- Config flow trace marker: `FLOW_TRACE_V3`.
- Flow logger prefix: `[ENOCEAN_FLOW]`.
- Runtime logs include parse/filter decisions and emitted event payload context.
