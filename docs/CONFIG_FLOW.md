# Config Flow

## Purpose

Drive commissioning in a deterministic way and create a config entry with:

- `mac_address`
- `security_key`

## Entry Point

The integration starts from the Bluetooth discovery step and shows an explicit
user confirmation (`bluetooth_confirm`) before commissioning stages begin.

## Commissioning Stages

1. `commissioning_hold_1`
   - Waits for `A0` press (energy bow), then hold window.
2. `commissioning_click_short`
   - Waits for short `A0` press.
3. `commissioning_hold_2`
   - Waits for `A0` press or direct commissioning payload (`len=26`).
4. `commissioning_release_2`
   - Waits confirmation action and final commissioning payload.
5. `commissioning_exit_mode`
   - Waits explicit `A1` press to confirm exit action.
6. `commissioning_active`
   - Creates config entry.

## State / Guards

- Flow progress is asynchronous (`show_progress` with progress task).
- On explicit Add click, flow state is reset and restarted from step 1.
- Stale mid-step re-entry is guarded and redirected to confirm path.
- Trace logs include:
  - `USER_ADD_CONFIRMED`
  - `USER_ADD_FORCE_RESTART`
  - `FLOW_CANCEL_TRACE`

## Important Behavior

If UI is closed without backend flow removal, progress task may continue.
Diagnosis must rely on backend logs (not only UI behavior).

