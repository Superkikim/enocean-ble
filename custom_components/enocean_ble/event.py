"""Event entities for EnOcean BLE buttons."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from homeassistant.components.event import EventDeviceClass, EventEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import button_mode
from .const import (
    ATTR_EVENT_TYPE,
    ATTR_MAC_ADDRESS,
    ATTR_PRESS_LOST,
    ATTR_REASON,
    ATTR_RECEIVER,
    ATTR_RSSI,
    ATTR_SEQUENCE_COUNTER,
    BUTTON_ENTITY_DESCRIPTIONS,
    MODE_EVENT_TYPES,
    RAW_EVENT_TYPES,
    SIGNAL_BUTTON_EVENT,
)
from .entity import switch_device_info

_LOGGER = logging.getLogger(__name__)

# Optional data some events carry (hold_release reason, raw_release press_lost).
_OPTIONAL_EVENT_DATA = (ATTR_REASON, ATTR_PRESS_LOST)


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
    """Set up one event entity per button, plus one raw event entity per button."""
    mode = button_mode(entry)
    _LOGGER.debug(
        "event_platform_setup entry_id=%s unique_id=%s mode=%s button_count=%s",
        entry.entry_id,
        entry.unique_id,
        mode,
        len(BUTTONS),
    )
    entities: list[EventEntity] = [
        EnOceanBleButtonEventEntity(entry, button, MODE_EVENT_TYPES[mode]) for button in BUTTONS
    ]
    entities.extend(EnOceanBleRawEventEntity(entry, button) for button in BUTTONS)
    async_add_entities(entities)


class EnOceanBleButtonEventEntity(EventEntity):
    """Event entity for one rocker button: the actions of the switch's button mode."""

    _attr_has_entity_name = True
    _attr_device_class = EventDeviceClass.BUTTON
    _attr_translation_key: str | None = None

    def __init__(
        self, entry: ConfigEntry, button: ButtonDescription, event_types: list[str]
    ) -> None:
        """Initialize the event entity."""
        self._entry = entry
        self._button_code = button.code
        if self._attr_translation_key is None:
            self._attr_name = button.name
        self._attr_unique_id = f"{entry.unique_id}_{button.code.lower()}"
        self._attr_event_types = list(event_types)

    @property
    def device_info(self) -> DeviceInfo:
        """Describe the parent EnOcean device."""
        return switch_device_info(self._entry)

    async def async_added_to_hass(self) -> None:
        """Subscribe to the events of this button."""
        signal = SIGNAL_BUTTON_EVENT.format(entry_id=self._entry.entry_id, button=self._button_code)
        self.async_on_remove(async_dispatcher_connect(self.hass, signal, self._async_handle_button_event))

    @callback
    def _async_handle_button_event(self, payload: dict[str, Any]) -> None:
        """Trigger the entity for the event types it declares, ignore the others."""
        event_type = payload.get(ATTR_EVENT_TYPE)
        if not isinstance(event_type, str) or event_type not in self.event_types:
            return

        event_data = {
            ATTR_RSSI: payload.get(ATTR_RSSI),
            ATTR_SEQUENCE_COUNTER: payload.get(ATTR_SEQUENCE_COUNTER),
            ATTR_MAC_ADDRESS: payload.get(ATTR_MAC_ADDRESS),
            ATTR_RECEIVER: payload.get(ATTR_RECEIVER),
        }
        event_data.update({key: payload[key] for key in _OPTIONAL_EVENT_DATA if key in payload})
        _LOGGER.debug(
            "event_entity_trigger entry_id=%s unique_id=%s event_type=%s event_data=%s",
            self._entry.entry_id,
            self.unique_id,
            event_type,
            event_data,
        )
        try:
            self._trigger_event(event_type, event_data)
            self.async_write_ha_state()
        except Exception:
            _LOGGER.exception(
                "event_entity_trigger_failed entry_id=%s unique_id=%s entity_id=%s event_type=%s",
                self._entry.entry_id,
                self.unique_id,
                self.entity_id,
                event_type,
            )


class EnOceanBleRawEventEntity(EnOceanBleButtonEventEntity):
    """Raw telegrams of one button (press and release as received), in every mode.

    Disabled by default: for users who build their own logic.
    """

    _attr_entity_registry_enabled_default = False
    _attr_translation_key = "raw"

    def __init__(self, entry: ConfigEntry, button: ButtonDescription) -> None:
        """Initialize the raw event entity."""
        super().__init__(entry, button, RAW_EVENT_TYPES)
        self._attr_translation_placeholders = {"button": button.code}
        self._attr_unique_id = f"{entry.unique_id}_{button.code.lower()}_raw"
