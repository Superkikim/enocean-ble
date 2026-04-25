"""EnOcean BLE integration."""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Callable
from time import monotonic
from typing import Any

from homeassistant.core import callback

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
    EVENT_BUTTON_EVENT,
    LONG_PRESS_SECONDS,
    PLATFORMS,
    RELEASE_TIMEOUT_SECONDS,
    SIGNAL_BUTTON_EVENT,
)
from .parser import parse_commissioning_telegram, parse_data_telegram

_LOGGER = logging.getLogger(__name__)

ButtonState = dict[str, float | int | bool | Callable[[], None] | None]


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
    security_key = entry.data.get(CONF_SECURITY_KEY, "")

    hass.data[DOMAIN][entry.entry_id] = {
        CONF_MAC_ADDRESS: mac_address,
        CONF_SECURITY_KEY: security_key,
        "last_sequence_counter": -1,
        "buttons": {},
    }
    _LOGGER.debug(
        "setup_entry entry_id=%s mac=%s security_key_present=%s security_key_fingerprint=%s",
        entry.entry_id,
        mac_address,
        bool(security_key),
        _fingerprint_key(security_key),
    )

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
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

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
    manufacturer_ids = sorted(service_info.manufacturer_data.keys())
    manufacturer_data = service_info.manufacturer_data.get(ENOCEAN_MANUFACTURER_ID)
    payload_len = len(manufacturer_data) if manufacturer_data is not None else 0
    _LOGGER.debug(
        "adv_received entry_id=%s configured_mac=%s adv_address=%s rssi=%s manufacturer_ids=%s enocean_payload_len=%s",
        entry.entry_id,
        configured_mac,
        service_info.address.upper(),
        service_info.rssi,
        manufacturer_ids,
        payload_len,
    )

    if service_info.address.upper() != configured_mac:
        _LOGGER.debug(
            "adv_filtered entry_id=%s reason=mac_mismatch configured_mac=%s adv_address=%s",
            entry.entry_id,
            configured_mac,
            service_info.address.upper(),
        )
        return
    if not configured_mac.startswith(ENOCEAN_MAC_PREFIX):
        _LOGGER.debug(
            "adv_filtered entry_id=%s reason=mac_prefix_mismatch configured_mac=%s expected_prefix=%s",
            entry.entry_id,
            configured_mac,
            ENOCEAN_MAC_PREFIX,
        )
        return

    if manufacturer_data is None:
        _LOGGER.debug(
            "adv_filtered entry_id=%s reason=enocean_manufacturer_data_missing manufacturer_id=%s",
            entry.entry_id,
            ENOCEAN_MANUFACTURER_ID,
        )
        return
    if len(manufacturer_data) < DATA_TELEGRAM_MIN_LENGTH:
        _LOGGER.debug(
            "adv_filtered entry_id=%s reason=telegram_too_short payload_len=%s min_len=%s",
            entry.entry_id,
            len(manufacturer_data),
            DATA_TELEGRAM_MIN_LENGTH,
        )
        return

    security_key_hex = str(entry_data.get(CONF_SECURITY_KEY, ""))
    if len(manufacturer_data) == 26:
        _LOGGER.debug(
            "commissioning_detected entry_id=%s mac=%s payload_len=%s",
            entry.entry_id,
            configured_mac,
            len(manufacturer_data),
        )
        try:
            commissioning = parse_commissioning_telegram(manufacturer_data)
        except ValueError:
            _LOGGER.debug(
                "commissioning_parse_failed entry_id=%s mac=%s payload_len=%s",
                entry.entry_id,
                configured_mac,
                len(manufacturer_data),
            )
            return

        if not security_key_hex:
            entry_data[CONF_SECURITY_KEY] = commissioning.security_key_hex
            entry_data["last_sequence_counter"] = commissioning.sequence_counter
            new_data = dict(entry.data)
            new_data[CONF_SECURITY_KEY] = commissioning.security_key_hex
            hass.config_entries.async_update_entry(entry, data=new_data)
            _LOGGER.info("EnOcean BLE auto-commissioned device %s", configured_mac)
            _LOGGER.debug(
                "commissioning_applied entry_id=%s mac=%s sequence_counter=%s key_fingerprint=%s",
                entry.entry_id,
                configured_mac,
                commissioning.sequence_counter,
                _fingerprint_key(commissioning.security_key_hex),
            )
            return

        _LOGGER.debug(
            "commissioning_seen_ignored entry_id=%s mac=%s sequence_counter=%s reason=entry_already_has_key key_fingerprint=%s",
            entry.entry_id,
            configured_mac,
            commissioning.sequence_counter,
            _fingerprint_key(security_key_hex),
        )
        return

    if not security_key_hex:
        _LOGGER.debug(
            "telegram_ignored_no_key entry_id=%s mac=%s payload_len=%s",
            entry.entry_id,
            configured_mac,
            len(manufacturer_data),
        )
        return

    _LOGGER.debug(
        "telegram_parse_attempt entry_id=%s mac=%s payload_len=%s key_fingerprint=%s",
        entry.entry_id,
        configured_mac,
        len(manufacturer_data),
        _fingerprint_key(security_key_hex),
    )
    try:
        parsed = parse_data_telegram(
            manufacturer_data,
            mac_address=configured_mac,
            security_key_hex=security_key_hex,
        )
    except ValueError as err:
        _LOGGER.debug(
            "telegram_parse_failed entry_id=%s mac=%s error=%s payload_len=%s",
            entry.entry_id,
            configured_mac,
            str(err),
            len(manufacturer_data),
        )
        return

    _LOGGER.debug(
        "telegram_parse_success entry_id=%s mac=%s buttons=%s event_type=%s sequence_counter=%s",
        entry.entry_id,
        configured_mac,
        parsed.buttons,
        parsed.event_type,
        parsed.sequence_counter,
    )
    if not parsed.buttons:
        _LOGGER.debug(
            "telegram_ignored_no_active_buttons entry_id=%s mac=%s sequence_counter=%s",
            entry.entry_id,
            configured_mac,
            parsed.sequence_counter,
        )
        return

    last_sequence = int(entry_data["last_sequence_counter"])
    if parsed.sequence_counter <= last_sequence:
        _LOGGER.debug(
            "telegram_deduplicated entry_id=%s mac=%s sequence_counter=%s last_sequence=%s",
            entry.entry_id,
            configured_mac,
            parsed.sequence_counter,
            last_sequence,
        )
        return

    entry_data["last_sequence_counter"] = parsed.sequence_counter
    for button in parsed.buttons:
        _emit_button_event(
            hass=hass,
            entry=entry,
            entry_data=entry_data,
            button=button,
            event_type=parsed.event_type,
            sequence_counter=parsed.sequence_counter,
            rssi=service_info.rssi,
            mac_address=configured_mac,
        )


def _emit_button_event(
    *,
    hass: Any,
    entry: Any,
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
        {
            "pressed_at": None,
            "long_fired": False,
            "last_single_press_seq": None,
            "last_received_seq": None,
            "cancel_long_cb": None,
            "cancel_timeout_cb": None,
        },
    )
    if not isinstance(state_any, dict):
        return
    state: ButtonState = state_any

    if event_type == "press":
        _cancel_all_timers(state)
        state["pressed_at"] = monotonic()
        state["last_received_seq"] = sequence_counter
        state["long_fired"] = False
        _LOGGER.debug(
            "event_press entry_id=%s mac=%s button=%s sequence_counter=%s",
            entry.entry_id,
            mac_address,
            button,
            sequence_counter,
        )
        _fire_event(
            hass=hass, entry=entry, button=button, event_type="press",
            sequence_counter=sequence_counter, rssi=rssi, mac_address=mac_address,
        )

        def _long_press_timer(_now: object) -> None:
            if state.get("pressed_at") is None:
                return
            state["long_fired"] = True
            state["cancel_long_cb"] = None
            _LOGGER.debug(
                "event_long_press entry_id=%s mac=%s button=%s", entry.entry_id, mac_address, button,
            )
            _fire_event(
                hass=hass, entry=entry, button=button, event_type="long_press",
                sequence_counter=sequence_counter, rssi=rssi, mac_address=mac_address,
            )

        def _release_timeout_timer(_now: object) -> None:
            if state.get("pressed_at") is None:
                return
            state["pressed_at"] = None
            state["long_fired"] = False
            state["cancel_timeout_cb"] = None
            _LOGGER.debug(
                "event_release_timeout entry_id=%s mac=%s button=%s", entry.entry_id, mac_address, button,
            )
            _fire_event(
                hass=hass, entry=entry, button=button, event_type="release_timeout",
                sequence_counter=sequence_counter, rssi=rssi, mac_address=mac_address,
            )

        state["cancel_long_cb"] = async_call_later(hass, LONG_PRESS_SECONDS, _long_press_timer)
        state["cancel_timeout_cb"] = async_call_later(hass, RELEASE_TIMEOUT_SECONDS, _release_timeout_timer)
        return

    if event_type == "release":
        if state.get("pressed_at") is not None:
            _cancel_all_timers(state)
            long_fired = bool(state.get("long_fired"))
            state["pressed_at"] = None
            state["long_fired"] = False
            state["last_received_seq"] = sequence_counter
            _LOGGER.debug(
                "event_release entry_id=%s mac=%s button=%s sequence_counter=%s long_fired=%s",
                entry.entry_id, mac_address, button, sequence_counter, long_fired,
            )
            _fire_event(
                hass=hass, entry=entry, button=button, event_type="release",
                sequence_counter=sequence_counter, rssi=rssi, mac_address=mac_address,
            )
            if long_fired:
                _fire_event(
                    hass=hass, entry=entry, button=button, event_type="long_release",
                    sequence_counter=sequence_counter, rssi=rssi, mac_address=mac_address,
                )
            else:
                if sequence_counter != state.get("last_single_press_seq"):
                    state["last_single_press_seq"] = sequence_counter
                    _fire_event(
                        hass=hass, entry=entry, button=button, event_type="single_press",
                        sequence_counter=sequence_counter, rssi=rssi, mac_address=mac_address,
                    )
        else:
            old_seq = state.get("last_received_seq")
            state["last_received_seq"] = sequence_counter
            _LOGGER.debug(
                "event_orphan_release entry_id=%s mac=%s button=%s sequence_counter=%s old_seq=%s",
                entry.entry_id, mac_address, button, sequence_counter, old_seq,
            )
            _fire_event(
                hass=hass, entry=entry, button=button, event_type="orphan_release",
                sequence_counter=sequence_counter, rssi=rssi, mac_address=mac_address,
            )
            is_coherent = (
                isinstance(old_seq, int)
                and sequence_counter - old_seq == 2
            )
            if is_coherent and sequence_counter != state.get("last_single_press_seq"):
                state["last_single_press_seq"] = sequence_counter
                _fire_event(
                    hass=hass, entry=entry, button=button, event_type="single_press",
                    sequence_counter=sequence_counter, rssi=rssi, mac_address=mac_address,
                )
        return

    _fire_event(
        hass=hass,
        entry=entry,
        button=button,
        event_type=event_type,
        sequence_counter=sequence_counter,
        rssi=rssi,
        mac_address=mac_address,
    )


def _cancel_all_timers(state: ButtonState) -> None:
    for key in ("cancel_long_cb", "cancel_timeout_cb"):
        cancel = state.get(key)
        if callable(cancel):
            cancel()
        state[key] = None


def _fire_event(
    *,
    hass: Any,
    entry: Any,
    button: str,
    event_type: str,
    sequence_counter: int,
    rssi: int | None,
    mac_address: str,
) -> None:
    from homeassistant.helpers.dispatcher import async_dispatcher_send

    @callback  # type: ignore[misc]
    def _async_dispatch() -> None:
        async_dispatcher_send(hass, SIGNAL_BUTTON_EVENT.format(entry_id=entry.entry_id), payload)
        hass.bus.async_fire(
            EVENT_BUTTON_EVENT,
            payload,
        )
        hass.bus.async_fire(
            EVENT_BUTTON_ACTION,
            payload,
        )

    payload = {
        ATTR_BUTTON: button,
        "event": event_type,
        ATTR_EVENT_TYPE: event_type,
        ATTR_RSSI: rssi,
        ATTR_SEQUENCE_COUNTER: sequence_counter,
        ATTR_MAC_ADDRESS: mac_address,
    }
    _LOGGER.debug(
        "event_emit entry_id=%s mac=%s button=%s event_type=%s sequence_counter=%s rssi=%s signal=%s",
        entry.entry_id,
        mac_address,
        button,
        event_type,
        sequence_counter,
        rssi,
        SIGNAL_BUTTON_EVENT.format(entry_id=entry.entry_id),
    )
    hass.add_job(_async_dispatch)


async def async_unload_entry(hass: Any, entry: Any) -> bool:
    """Unload a config entry."""
    await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    hass.data[DOMAIN].pop(entry.entry_id, None)
    _LOGGER.debug("unload_entry entry_id=%s", entry.entry_id)
    return True


def _fingerprint_key(key_hex: str) -> str:
    """Return a short, non-reversible key fingerprint for debug logs."""
    if not key_hex:
        return "none"
    digest = hashlib.sha256(key_hex.encode("utf-8")).hexdigest()
    return digest[:8]
