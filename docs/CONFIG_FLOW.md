# Config Flow

## Purpose

Commission one EnOcean BLE switch from Bluetooth discovery and create one config entry with:

- `mac_address`
- `security_key`

## Current Flow (Implemented)

1. `bluetooth` (discovery)
- Starts from Bluetooth discovery.
- Stores discovered MAC/title and initializes trace state.

2. `commissioning` (progress)
- Shows progress instructions to the user.
- Waits for a commissioning telegram (`len=26`) with a `120s` timeout.
- On success, parses and validates payload MAC and stores `security_key`.
- On timeout/invalid payload, returns a retry form on the same step.

3. `bluetooth_confirm` (explicit submit)
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
