# Architecture

## Runtime Components

- `config_flow.py`
  - Handles BLE discovery and commissioning flow steps.
  - Extracts and validates security key from commissioning payload.
- `__init__.py`
  - Registers Bluetooth callback for configured devices.
  - Parses telegrams and emits integration events.
- `parser.py`
  - Decodes EnOcean BLE telegrams and commissioning telegrams.
- `crypto.py`
  - Cryptographic checks (MIC validation path).
- `event.py`
  - Exposes per-button Home Assistant event entities.
- `const.py`
  - Domain constants, button/status masks, protocol constants.

## Data Path

1. BLE advertisement received by Home Assistant Bluetooth stack.
2. Integration filters by configured MAC and manufacturer payload.
3. Parser decodes payload into semantic button events.
4. Runtime emits integration signal/event payload.
5. Per-button event entities filter and publish final event state.

## Security Path

1. Commissioning telegram provides per-device key material.
2. Key is stored in config entry data.
3. Runtime parser uses key for telegram integrity checks.

## Logging Strategy

- Prefix: `[ENOCEAN_FLOW]` for config flow lifecycle logs.
- Flow cancellation trace marker: `FLOW_CANCEL_TRACE`.
- Runtime parser and entity logs are namespaced by module logger.

