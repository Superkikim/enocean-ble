# Project Overview

## Name

`enocean_ble` - Home Assistant custom integration for EnOcean BLE kinetic switches based on `PTM 215B/PTM 216B`.

## Goal

Provide reliable passive BLE reception of button telegrams and expose them in Home Assistant with UX-friendly automation options.

## Supported Scope

- Discovery-driven commissioning flow.
- Commissioning key extraction from `len=26` telegram.
- Runtime telegram parsing and MIC validation.
- Bus events:
- `enocean_ble_button_event` (recommended)
- `enocean_ble_button_action` (legacy)
- Event entities for `A0`, `A1`, `B0`, `B1`.
- Sensor entities for latest button event per button.
- Event types:
- `press`
- `release`
- `long_press`
- `long_release`

## Non-Goals / Limits

- No BLE GATT write/configuration to switches.
- No remote factory reset.
- Delivery of radio events depends on BLE environment quality (2.4 GHz interference, distance, attenuation).

## Repository Layout

- `custom_components/enocean_ble`: integration implementation.
- `tests`: unit tests.
- `scripts`: helper scripts.
- `docs`: technical docs/runbooks.
