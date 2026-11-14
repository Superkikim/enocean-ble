"""Sensor entities for EnOcean BLE switches: diagnostics, and Legacy last-event sensors."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import SIGNAL_STRENGTH_DECIBELS_MILLIWATT, EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import button_mode
from .const import (
    ATTR_EVENT_TYPE,
    ATTR_MAC_ADDRESS,
    ATTR_RECEIVER,
    ATTR_RSSI,
    ATTR_SEQUENCE_COUNTER,
    BUTTON_ENTITY_DESCRIPTIONS,
    DOMAIN,
    MODE_LEGACY,
    SIGNAL_BUTTON_EVENT,
    SIGNAL_DEVICE_UPDATE,
    SUPPORTED_EVENT_TYPES,
)
from .entity import switch_device_info

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ButtonDescription:
    """Description for one EnOcean button sensor."""

    code: str
    name: str


BUTTONS: tuple[ButtonDescription, ...] = tuple(
    ButtonDescription(code=code, name=name) for code, name in BUTTON_ENTITY_DESCRIPTIONS.items()
)


def _legacy_sensor_unique_id(entry: ConfigEntry, code: str) -> str:
    return f"{entry.unique_id}_{code.lower()}_event"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the diagnostic sensors, and the last-event sensors in Legacy mode."""
    entities: list[SensorEntity] = [
        EnOceanBleSignalSensor(entry),
        EnOceanBleLastSeenSensor(entry),
        EnOceanBleReceiverSensor(entry),
        EnOceanBleLostMessagesSensor(entry),
    ]
    if button_mode(entry) == MODE_LEGACY:
        entities.extend(EnOceanBleButtonEventSensor(entry, button) for button in BUTTONS)
    else:
        # Replaced by the event entities and the "Event received" trigger.
        registry = er.async_get(hass)
        for button in BUTTONS:
            entity_id = registry.async_get_entity_id(
                "sensor", DOMAIN, _legacy_sensor_unique_id(entry, button.code)
            )
            if entity_id is not None:
                registry.async_remove(entity_id)
    async_add_entities(entities)


class EnOceanBleButtonEventSensor(SensorEntity):
    """Legacy mode: the latest event of one physical button."""

    _attr_has_entity_name = True
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = sorted(SUPPORTED_EVENT_TYPES)
    _attr_native_value: str | None = None

    def __init__(self, entry: ConfigEntry, button: ButtonDescription) -> None:
        """Initialize the sensor entity."""
        self._entry = entry
        self._button_code = button.code
        self._attr_name = f"{button.name} event"
        self._attr_unique_id = _legacy_sensor_unique_id(entry, button.code)
        self._attr_extra_state_attributes: dict[str, Any] = {}

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
        """Update the sensor state when a button event is received."""
        event_type = payload.get(ATTR_EVENT_TYPE)
        if not isinstance(event_type, str) or event_type not in SUPPORTED_EVENT_TYPES:
            return

        self._attr_native_value = event_type
        self._attr_extra_state_attributes = {
            ATTR_RSSI: payload.get(ATTR_RSSI),
            ATTR_SEQUENCE_COUNTER: payload.get(ATTR_SEQUENCE_COUNTER),
            ATTR_MAC_ADDRESS: payload.get(ATTR_MAC_ADDRESS),
            ATTR_RECEIVER: payload.get(ATTR_RECEIVER),
        }
        self.async_write_ha_state()


class _EnOceanBleDiagnosticSensor(SensorEntity):
    """A diagnostic value of the switch, updated on each accepted telegram.

    Disabled by default. Values come from the first receiver that delivered the telegram.
    """

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False
    _key: str
    _name: str

    def __init__(self, entry: ConfigEntry) -> None:
        """Initialize the sensor entity."""
        self._entry = entry
        self._attr_name = self._name
        self._attr_unique_id = f"{entry.unique_id}_{self._key}"

    @property
    def device_info(self) -> DeviceInfo:
        """Describe the parent EnOcean device."""
        return switch_device_info(self._entry)

    def _entry_data(self) -> dict[str, Any]:
        data: dict[str, Any] = self.hass.data.get(DOMAIN, {}).get(self._entry.entry_id, {})
        return data

    async def async_added_to_hass(self) -> None:
        """Subscribe to the switch's diagnostic updates."""
        self._update_from(self._entry_data())
        signal = SIGNAL_DEVICE_UPDATE.format(entry_id=self._entry.entry_id)
        self.async_on_remove(async_dispatcher_connect(self.hass, signal, self._async_handle_update))

    @callback
    def _async_handle_update(self) -> None:
        self._update_from(self._entry_data())
        self.async_write_ha_state()

    def _update_from(self, data: dict[str, Any]) -> None:
        raise NotImplementedError


class EnOceanBleSignalSensor(_EnOceanBleDiagnosticSensor):
    """Signal strength of the last telegram."""

    _key = "signal"
    _name = "Signal"
    _attr_device_class = SensorDeviceClass.SIGNAL_STRENGTH
    _attr_native_unit_of_measurement = SIGNAL_STRENGTH_DECIBELS_MILLIWATT
    _attr_state_class = SensorStateClass.MEASUREMENT

    def _update_from(self, data: dict[str, Any]) -> None:
        self._attr_native_value = data.get("last_rssi")


class EnOceanBleLastSeenSensor(_EnOceanBleDiagnosticSensor):
    """Time of the last telegram."""

    _key = "last_seen"
    _name = "Last seen"
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def _update_from(self, data: dict[str, Any]) -> None:
        value = data.get("last_seen")
        self._attr_native_value = value if isinstance(value, datetime) else None


class EnOceanBleReceiverSensor(_EnOceanBleDiagnosticSensor):
    """Bluetooth adapter or proxy that delivered the last telegram first."""

    _key = "receiver"
    _name = "Receiver"

    def _update_from(self, data: dict[str, Any]) -> None:
        self._attr_native_value = data.get("last_receiver")


class EnOceanBleLostMessagesSensor(_EnOceanBleDiagnosticSensor):
    """Telegrams no receiver got, found from gaps in the sequence counter."""

    _key = "lost_messages"
    _name = "Lost messages"
    _attr_state_class = SensorStateClass.TOTAL_INCREASING

    def _update_from(self, data: dict[str, Any]) -> None:
        self._attr_native_value = int(data.get("lost_messages", 0))
