# Troubleshooting

## No BLE events
- Confirm Bluetooth is enabled in Home Assistant host.
- Verify switch is within range and actuated.
- Check integration logs with debug level (keys remain redacted).

## Invalid QR/NFC data
- Re-scan the code and ensure full raw string is pasted.
- Confirm device model is PTM215B/PTM216B.

## Migration from Casambi
- Perform factory reset before onboarding.
- Disable old Casambi automations to avoid duplicate triggers.
