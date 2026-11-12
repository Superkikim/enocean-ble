"""Pytest bootstrap for local path resolution and HA module stubs."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Stub out homeassistant packages so tests run without a full HA installation.
_HA_MODULES = [
    "homeassistant",
    "homeassistant.core",
    "homeassistant.components",
    "homeassistant.components.bluetooth",
    "homeassistant.config_entries",
    "homeassistant.data_entry_flow",
    "homeassistant.helpers",
    "homeassistant.helpers.event",
    "homeassistant.helpers.dispatcher",
]
for _mod in _HA_MODULES:
    sys.modules.setdefault(_mod, MagicMock())
