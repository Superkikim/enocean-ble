"""Basic manifest sanity checks for custom integration structure."""

from __future__ import annotations

import json
from pathlib import Path

MANIFEST_PATH = Path("custom_components/enocean_ble/manifest.json")
REQUIRED_KEYS = {
    "domain",
    "name",
    "version",
    "documentation",
    "issue_tracker",
    "config_flow",
    "iot_class",
}


def main() -> int:
    if not MANIFEST_PATH.exists():
        print(f"Manifest not found: {MANIFEST_PATH}")
        return 1

    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    missing = sorted(REQUIRED_KEYS - manifest.keys())
    if missing:
        print(f"Manifest missing required keys: {', '.join(missing)}")
        return 1

    if manifest["domain"] != "enocean_ble":
        print("Manifest domain must be enocean_ble")
        return 1

    print("Manifest sanity checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
