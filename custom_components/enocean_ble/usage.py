"""Find the automations and scripts that use a switch, for the Legacy repair."""

from __future__ import annotations

import json
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .const import DOMAIN

_LEGACY_SENSOR_SUFFIX = "_event"
# Templates such as integration_entities('enocean_ble') name no entity at all.
_INTEGRATION_NEEDLE = DOMAIN


def _switch_entries(hass: HomeAssistant, entry: ConfigEntry) -> list[er.RegistryEntry]:
    return er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)


def _legacy_sensor_ids(entries: list[er.RegistryEntry]) -> list[str]:
    return [
        e.entity_id
        for e in entries
        if e.domain == "sensor" and str(e.unique_id).endswith(_LEGACY_SENSOR_SUFFIX)
    ]


def _config_text(raw_config: Any) -> str:
    try:
        return json.dumps(raw_config, default=str)
    except (TypeError, ValueError):
        return str(raw_config)


def _users_in(
    hass: HomeAssistant,
    domain: str,
    entity_ids: set[str],
    device_ids: set[str],
    needles: list[str],
) -> list[str]:
    """Entities of an automation or script component that reference the switch.

    Structured references (entity or device in a trigger, condition, action or target) come from
    Home Assistant itself. The text search adds what it cannot see: an entity id written inside a
    template, or ``integration_entities('enocean_ble')``.
    """
    component = hass.data.get(domain)
    found: dict[str, str] = {}
    for item in getattr(component, "entities", ()):
        referenced = set(getattr(item, "referenced_entities", ()) or ())
        referenced_devices = set(getattr(item, "referenced_devices", ()) or ())
        in_config = _config_text(getattr(item, "raw_config", None))
        if (
            referenced & entity_ids
            or referenced_devices & device_ids
            or any(needle in in_config for needle in needles)
        ):
            found[item.entity_id] = str(getattr(item, "name", None) or item.entity_id)
    return [f"- {name} (`{entity_id}`)" for entity_id, name in sorted(found.items())]


def find_switch_users(hass: HomeAssistant, entry: ConfigEntry) -> list[str]:
    """Markdown list items for the automations and scripts that use the switch."""
    entries = _switch_entries(hass, entry)
    legacy_ids = _legacy_sensor_ids(entries)
    entity_ids = {e.entity_id for e in entries}
    device_ids = {e.device_id for e in entries if e.device_id}
    needles = [*legacy_ids, _INTEGRATION_NEEDLE]
    return [
        *_users_in(hass, "automation", entity_ids, device_ids, needles),
        *_users_in(hass, "script", entity_ids, device_ids, needles),
    ]
