"""Event entities for EnOcean BLE buttons."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from homeassistant.components.event import EventDeviceClass, EventEntity
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
)

EVENT_TYPES = ["press", "release", "long_press", "long_release"]
_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ButtonDescription:
    """Description for one EnOcean button entity."""

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
    """Set up EnOcean BLE event entities."""
    _LOGGER.debug(
        "event_platform_setup entry_id=%s unique_id=%s button_count=%s",
        entry.entry_id,
        entry.unique_id,
        len(BUTTONS),
    )
    async_add_entities(EnOceanBleButtonEventEntity(entry, button) for button in BUTTONS)


class EnOceanBleButtonEventEntity(EventEntity):  # type: ignore[misc]
    """Event entity for one physical EnOcean BLE rocker button."""

    _attr_has_entity_name = True
    _attr_device_class = EventDeviceClass.BUTTON
    _attr_event_types = EVENT_TYPES

    def __init__(self, entry: ConfigEntry, button: ButtonDescription) -> None:
        """Initialize the event entity."""
        self._entry = entry
        self._button_code = button.code
        self._attr_name = button.name
        self._attr_unique_id = f"{entry.unique_id}_{button.code.lower()}"

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
            "event_entity_attached entry_id=%s unique_id=%s button=%s signal=%s",
            self._entry.entry_id,
            self.unique_id,
            self._button_code,
            signal,
        )
        self.async_on_remove(async_dispatcher_connect(self.hass, signal, self._async_handle_button_event))

    @callback  # type: ignore[misc]
    def _async_handle_button_event(self, payload: dict[str, Any]) -> None:
        """Forward event updates to this button entity."""
        payload_button = payload.get(ATTR_BUTTON)
        _LOGGER.debug(
            "event_entity_payload_received entry_id=%s unique_id=%s button=%s payload_button=%s payload=%s",
            self._entry.entry_id,
            self.unique_id,
            self._button_code,
            payload_button,
            payload,
        )
        if payload_button != self._button_code:
            _LOGGER.debug(
                "event_entity_payload_ignored entry_id=%s unique_id=%s button=%s reason=button_mismatch payload_button=%s",
                self._entry.entry_id,
                self.unique_id,
                self._button_code,
                payload_button,
            )
            return

        event_type = payload.get(ATTR_EVENT_TYPE)
        if not isinstance(event_type, str):
            _LOGGER.debug(
                "event_entity_payload_ignored entry_id=%s unique_id=%s button=%s reason=invalid_event_type payload_event_type=%s",
                self._entry.entry_id,
                self.unique_id,
                self._button_code,
                event_type,
            )
            return

        event_data = {
            ATTR_RSSI: payload.get(ATTR_RSSI),
            ATTR_SEQUENCE_COUNTER: payload.get(ATTR_SEQUENCE_COUNTER),
            ATTR_MAC_ADDRESS: payload.get(ATTR_MAC_ADDRESS),
        }
        _LOGGER.debug(
            "event_entity_trigger entry_id=%s unique_id=%s button=%s event_type=%s event_data=%s",
            self._entry.entry_id,
            self.unique_id,
            self._button_code,
            event_type,
            event_data,
        )
        try:
            self._trigger_event(event_type, event_data)
            self.async_write_ha_state()
        except Exception:
            _LOGGER.exception(
                "event_entity_trigger_failed entry_id=%s unique_id=%s button=%s entity_id=%s event_type=%s payload=%s",
                self._entry.entry_id,
                self.unique_id,
                self._button_code,
                self.entity_id,
                event_type,
                payload,
            )
            return
        _LOGGER.debug(
            "event_entity_state_written entry_id=%s unique_id=%s button=%s event_type=%s",
            self._entry.entry_id,
            self.unique_id,
            self._button_code,
            event_type,
        )
