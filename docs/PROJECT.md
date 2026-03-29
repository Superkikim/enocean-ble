# Project Overview

## Name

`enocean_ble` - Home Assistant custom integration for EnOcean BLE switches.

## Goal

Provide reliable passive BLE reception of EnOcean PTM button telegrams and
expose them as Home Assistant event entities.

## Supported Devices

- EnOcean PTM215B
- EnOcean PTM216B

## Current Functional Scope

- Bluetooth discovery-driven config flow.
- Commissioning key extraction from commissioning telegrams.
- Runtime telegram parsing and MIC verification.
- Event entities for `A0`, `A1`, `B0`, `B1`.
- Event types: `press`, `release`, `long_press`, `long_release`.

## Non-Goals / Limits

- No BLE GATT write/configuration of PTM devices.
- No remote factory reset of a switch from the integration.
- Behavior depends on BLE advertisement quality (RSSI/interference/environment).

## Repository Layout

- `custom_components/enocean_ble`: integration implementation.
- `tests`: unit tests for parser/crypto/runtime behavior.
- `scripts`: helper scripts for local diagnostics.
- `docs`: project documentation and runbooks.

