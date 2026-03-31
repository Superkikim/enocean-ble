"""Sensor entities for EnOcean BLE button last event state."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    ATTR_BUTTON,
    ATTR_EVENT_TYPE,
    ATTR_MAC_ADDRESS,
    ATTR_RSSI,
    ATTR_SEQUENCE_COUNTER,
    BUTTON_ENTITY_DESCRIPTIONS,
    CONF_MAC_ADDRESS,
    DOMAIN,
    INTEGRATION_NAME,
    SIGNAL_BUTTON_EVENT,
    SUPPORTED_EVENT_TYPES,
)

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ButtonDescription:
    """Description for one EnOcean button sensor."""

    code: str
    name: str


BUTTONS: tuple[ButtonDescription, ...] = tuple(
    ButtonDescription(code=code, name=name) for code, name in BUTTON_ENTITY_DESCRIPTIONS.items()
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up EnOcean BLE sensor entities."""
    _LOGGER.debug(
        "sensor_platform_setup entry_id=%s unique_id=%s button_count=%s",
        entry.entry_id,
        entry.unique_id,
        len(BUTTONS),
    )
    async_add_entities(EnOceanBleButtonEventSensor(entry, button) for button in BUTTONS)


class EnOceanBleButtonEventSensor(SensorEntity):  # type: ignore[misc]
    """Sensor entity exposing the latest event for one physical button."""

    _attr_has_entity_name = True
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = sorted(SUPPORTED_EVENT_TYPES)
    _attr_native_value: str | None = None

    def __init__(self, entry: ConfigEntry, button: ButtonDescription) -> None:
        """Initialize the sensor entity."""
        self._entry = entry
        self._button_code = button.code
        self._attr_name = f"{button.name} event"
        self._attr_unique_id = f"{entry.unique_id}_{button.code.lower()}_event"
        self._attr_extra_state_attributes: dict[str, Any] = {}

    @property
    def device_info(self) -> DeviceInfo:
        """Describe the parent EnOcean device."""
        mac_address = self._entry.data[CONF_MAC_ADDRESS]
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry.entry_id)},
            connections={(dr.CONNECTION_BLUETOOTH, mac_address)},
            name=self._entry.title,
            manufacturer="EnOcean",
            model=INTEGRATION_NAME,
        )

    async def async_added_to_hass(self) -> None:
        """Subscribe to parsed telegram events for this config entry."""
        signal = SIGNAL_BUTTON_EVENT.format(entry_id=self._entry.entry_id)
        _LOGGER.debug(
            "sensor_entity_attached entry_id=%s unique_id=%s button=%s signal=%s",
            self._entry.entry_id,
            self.unique_id,
            self._button_code,
            signal,
        )
        self.async_on_remove(async_dispatcher_connect(self.hass, signal, self._async_handle_button_event))

    @callback  # type: ignore[misc]
    def _async_handle_button_event(self, payload: dict[str, Any]) -> None:
        """Update the sensor state when a button event is received."""
        if payload.get(ATTR_BUTTON) != self._button_code:
            return

        event_type = payload.get(ATTR_EVENT_TYPE)
        if not isinstance(event_type, str) or event_type not in SUPPORTED_EVENT_TYPES:
            return

        self._attr_native_value = event_type
        self._attr_extra_state_attributes = {
            ATTR_RSSI: payload.get(ATTR_RSSI),
            ATTR_SEQUENCE_COUNTER: payload.get(ATTR_SEQUENCE_COUNTER),
            ATTR_MAC_ADDRESS: payload.get(ATTR_MAC_ADDRESS),
        }
        self.async_write_ha_state()
