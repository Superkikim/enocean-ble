"""Every translation file has the same keys, and every key the code uses exists."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from custom_components.enocean_ble.event import (
    BUTTONS,
    EnOceanBleButtonEventEntity,
    EnOceanBleRawEventEntity,
)
from custom_components.enocean_ble.sensor import (
    EnOceanBleButtonEventSensor,
    EnOceanBleLastSeenSensor,
    EnOceanBleLostMessagesSensor,
    EnOceanBleReceiverSensor,
    EnOceanBleSignalSensor,
)

TRANSLATIONS = Path(__file__).resolve().parents[1] / "custom_components/enocean_ble/translations"
FILES = sorted(TRANSLATIONS.glob("*.json"))


def _keys(data: dict[str, Any], prefix: str = "") -> set[str]:
    keys: set[str] = set()
    for key, value in data.items():
        keys.add(prefix + key)
        if isinstance(value, dict):
            keys |= _keys(value, f"{prefix}{key}.")
    return keys


def test_all_ten_languages_are_present() -> None:
    assert [f.stem for f in FILES] == ["cs", "de", "en", "es", "fr", "it", "nl", "pl", "pt-BR", "sv"]


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.stem)
def test_same_keys_as_english(path: Path) -> None:
    english = _keys(json.loads((TRANSLATIONS / "en.json").read_text(encoding="utf-8")))
    assert _keys(json.loads(path.read_text(encoding="utf-8"))) == english


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.stem)
def test_entity_names_and_placeholders_are_translated(path: Path) -> None:
    entry = SimpleNamespace(unique_id="E2:15:00:00:19:B8")
    entities: list[Any] = [
        EnOceanBleRawEventEntity(entry, BUTTONS[0]),  # type: ignore[arg-type]
        EnOceanBleButtonEventSensor(entry, BUTTONS[0]),  # type: ignore[arg-type]
        EnOceanBleSignalSensor(entry),  # type: ignore[arg-type]
        EnOceanBleLastSeenSensor(entry),  # type: ignore[arg-type]
        EnOceanBleReceiverSensor(entry),  # type: ignore[arg-type]
        EnOceanBleLostMessagesSensor(entry),  # type: ignore[arg-type]
    ]
    translations = json.loads(path.read_text(encoding="utf-8"))["entity"]
    for entity in entities:
        domain = "event" if isinstance(entity, EnOceanBleButtonEventEntity) else "sensor"
        name = translations[domain][entity.translation_key]["name"]
        for placeholder in getattr(entity, "translation_placeholders", {}):
            assert "{" + placeholder + "}" in name
