# Troubleshooting

## Device is discovered but commissioning does not complete

- Keep the switch close to the HA Bluetooth receiver for commissioning.
- Follow the exact button sequence shown in the progress step.
- Wait for the confirm screen, press another button (not button 1), then submit.
- If timeout repeats, retry.
- If repeated failures persist, review reset guidance in `README.md` (factory reset disclaimer).

## Device gets recreated immediately after deletion

- This usually means the switch is still sending commissioning telegrams (`len=26`).
- Exit commissioning mode on the physical switch before deleting/re-adding.

## Automations do not trigger

- Prefer state triggers on `sensor.<device>_<button>_event` for UX simplicity.
- Or use event triggers on `enocean_ble_button_event` for full payload filtering.
- Verify current event payload with Developer Tools -> Events.

## Missing logs

- Enable debug for `custom_components.enocean_ble`.
- Check container logs for `FLOW_TRACE_V3` and runtime parser lines.

## About occasional missed actions

BLE on 2.4 GHz can drop packets in real environments. This is expected behavior and can happen on any passive BLE button setup.
