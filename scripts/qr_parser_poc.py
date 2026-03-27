"""Standalone QR parser proof-of-concept for Phase B."""

from __future__ import annotations

import argparse

from custom_components.enocean_ble.parser import parse_onboarding_blob


def main() -> int:
    parser = argparse.ArgumentParser(description="Parse EnOcean onboarding QR/NFC blob")
    parser.add_argument("raw", help="Raw QR/NFC string")
    args = parser.parse_args()

    parsed = parse_onboarding_blob(args.raw)
    print(f"mac_address={parsed.mac_address}")
    print(f"security_key_hex={parsed.security_key_hex}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
