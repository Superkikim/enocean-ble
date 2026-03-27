"""EnOcean BLE integration."""

from __future__ import annotations

import logging
from collections.abc import Callable
from time import monotonic
from typing import Any

from .const import (
    ATTR_BUTTON,
    ATTR_EVENT_TYPE,
    ATTR_MAC_ADDRESS,
    ATTR_RSSI,
    ATTR_SEQUENCE_COUNTER,
    CONF_MAC_ADDRESS,
    CONF_SECURITY_KEY,
    DATA_TELEGRAM_MIN_LENGTH,
    DOMAIN,
    ENOCEAN_MAC_PREFIX,
    ENOCEAN_MANUFACTURER_ID,
    EVENT_BUTTON_ACTION,
    LONG_PRESS_SECONDS,
)
from .parser import parse_data_telegram

_LOGGER = logging.getLogger(__name__)

ButtonState = dict[str, float | bool | Callable[[], None] | None]


async def async_setup(hass: Any, config: dict[str, Any]) -> bool:
    """Set up EnOcean BLE integration."""
    hass.data.setdefault(DOMAIN, {})
    return True


async def async_setup_entry(hass: Any, entry: Any) -> bool:
    """Set up EnOcean BLE from a config entry."""
    from homeassistant.components.bluetooth import (
        BluetoothScanningMode,
        async_register_callback,
    )

    hass.data.setdefault(DOMAIN, {})

    mac_address = entry.data[CONF_MAC_ADDRESS]
    security_key = entry.data[CONF_SECURITY_KEY]

    hass.data[DOMAIN][entry.entry_id] = {
        CONF_MAC_ADDRESS: mac_address,
        CONF_SECURITY_KEY: security_key,
        "last_sequence_counter": -1,
        "buttons": {},
    }

    def _async_handle_advertisement(service_info: Any, _change: int) -> None:
        _process_advertisement(hass, entry, service_info)

    entry.async_on_unload(
        async_register_callback(
            hass,
            _async_handle_advertisement,
            {"manufacturer_id": ENOCEAN_MANUFACTURER_ID},
            BluetoothScanningMode.PASSIVE,
        )
    )

    _LOGGER.info("EnOcean BLE device configured: %s", mac_address)
    return True


def _process_advertisement(
    hass: Any,
    entry: Any,
    service_info: Any,
) -> None:
    """Process BLE advertisements and emit Home Assistant button events."""
    entry_data = hass.data[DOMAIN][entry.entry_id]
    configured_mac = str(entry_data[CONF_MAC_ADDRESS]).upper()

    if service_info.address.upper() != configured_mac:
        return
    if not configured_mac.startswith(ENOCEAN_MAC_PREFIX):
        return

    manufacturer_data = service_info.manufacturer_data.get(ENOCEAN_MANUFACTURER_ID)
    if manufacturer_data is None or len(manufacturer_data) < DATA_TELEGRAM_MIN_LENGTH:
        return

    try:
        parsed = parse_data_telegram(
            manufacturer_data,
            mac_address=configured_mac,
            security_key_hex=str(entry_data[CONF_SECURITY_KEY]),
        )
    except ValueError:
        _LOGGER.debug("Dropped invalid telegram for %s", configured_mac)
        return

    last_sequence = int(entry_data["last_sequence_counter"])
    if parsed.sequence_counter <= last_sequence:
        return

    entry_data["last_sequence_counter"] = parsed.sequence_counter
    _emit_button_event(
        hass=hass,
        entry_data=entry_data,
        button=parsed.button,
        event_type=parsed.event_type,
        sequence_counter=parsed.sequence_counter,
        rssi=service_info.rssi,
        mac_address=configured_mac,
    )


def _emit_button_event(
    *,
    hass: Any,
    entry_data: dict[str, Any],
    button: str,
    event_type: str,
    sequence_counter: int,
    rssi: int | None,
    mac_address: str,
) -> None:
    from homeassistant.helpers.event import async_call_later

    buttons = entry_data["buttons"]
    if not isinstance(buttons, dict):
        return

    state_any = buttons.setdefault(
        button,
        {"pressed_at": None, "long_fired": False, "cancel_long_cb": None},
    )
    if not isinstance(state_any, dict):
        return
    state: ButtonState = state_any

    if event_type == "press":
        _cancel_long_timer(state)
        state["pressed_at"] = monotonic()
        state["long_fired"] = False

        def _long_press_timer(_now: object) -> None:
            if state.get("pressed_at") is None:
                return
            state["long_fired"] = True
            _fire_event(
                hass=hass,
                button=button,
                event_type="long_press",
                sequence_counter=sequence_counter,
                rssi=rssi,
                mac_address=mac_address,
            )

        state["cancel_long_cb"] = async_call_later(hass, LONG_PRESS_SECONDS, _long_press_timer)
        _fire_event(
            hass=hass,
            button=button,
            event_type="press",
            sequence_counter=sequence_counter,
            rssi=rssi,
            mac_address=mac_address,
        )
        return

    if event_type == "release":
        _cancel_long_timer(state)
        long_fired = bool(state.get("long_fired"))
        state["pressed_at"] = None
        state["long_fired"] = False

        _fire_event(
            hass=hass,
            button=button,
            event_type="long_release" if long_fired else "release",
            sequence_counter=sequence_counter,
            rssi=rssi,
            mac_address=mac_address,
        )
        return

    _fire_event(
        hass=hass,
        button=button,
        event_type=event_type,
        sequence_counter=sequence_counter,
        rssi=rssi,
        mac_address=mac_address,
    )


def _cancel_long_timer(state: ButtonState) -> None:
    cancel = state.get("cancel_long_cb")
    if callable(cancel):
        cancel()
    state["cancel_long_cb"] = None


def _fire_event(
    *,
    hass: Any,
    button: str,
    event_type: str,
    sequence_counter: int,
    rssi: int | None,
    mac_address: str,
) -> None:
    hass.bus.async_fire(
        EVENT_BUTTON_ACTION,
        {
            ATTR_BUTTON: button,
            ATTR_EVENT_TYPE: event_type,
            ATTR_RSSI: rssi,
            ATTR_SEQUENCE_COUNTER: sequence_counter,
            ATTR_MAC_ADDRESS: mac_address,
        },
    )


async def async_unload_entry(hass: Any, entry: Any) -> bool:
    """Unload a config entry."""
    hass.data[DOMAIN].pop(entry.entry_id, None)
    return True
