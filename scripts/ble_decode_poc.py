"""Standalone BLE telegram decoder for Phase B validation."""

from __future__ import annotations

import argparse

from custom_components.enocean_ble.parser import parse_data_telegram


def main() -> int:
    parser = argparse.ArgumentParser(description="Decode EnOcean BLE telegram")
    parser.add_argument("--mac", required=True, help="MAC address, e.g. E2:15:AA:BB:CC:DD")
    parser.add_argument("--key", required=True, help="AES-128 key hex")
    parser.add_argument("--telegram", required=True, help="Telegram hex bytes")
    args = parser.parse_args()

    telegram = bytes.fromhex(args.telegram)
    parsed = parse_data_telegram(telegram, mac_address=args.mac, security_key_hex=args.key)

    print(f"sequence_counter={parsed.sequence_counter}")
    print(f"button={parsed.button}")
    print(f"event_type={parsed.event_type}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
