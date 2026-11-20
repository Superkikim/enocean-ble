"""Shared helpers for EnOcean BLE entities."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import DeviceInfo

from .const import CONF_MAC_ADDRESS, DOMAIN, INTEGRATION_NAME


def switch_device_info(entry: ConfigEntry) -> DeviceInfo:
    """Describe the EnOcean switch every entity of an entry belongs to."""
    mac_address = entry.data[CONF_MAC_ADDRESS]
    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        connections={(dr.CONNECTION_BLUETOOTH, mac_address)},
        name=entry.title,
        manufacturer="EnOcean",
        model=INTEGRATION_NAME,
    )
