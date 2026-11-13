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
    ATTR_RECEIVER,
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
    STORAGE_SAVE_DELAY_SECONDS,
    STORAGE_VERSION,
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

    # Without the stored counter, the advertisement Home Assistant keeps in its
    # Bluetooth cache is replayed at startup and taken for a new telegram.
    store = _sequence_store(hass, entry)
    stored = await store.async_load()
    last_sequence_counter = int(stored.get("last_sequence_counter", -1)) if stored else -1

    hass.data[DOMAIN][entry.entry_id] = {
        CONF_MAC_ADDRESS: mac_address,
        CONF_SECURITY_KEY: security_key,
        "store": store,
        "last_sequence_counter": last_sequence_counter,
        "buttons": {},
    }
    _LOGGER.debug(
        "setup_entry entry_id=%s mac=%s last_sequence_counter=%s security_key_present=%s security_key_fingerprint=%s",
        entry.entry_id,
        mac_address,
        last_sequence_counter,
        bool(security_key),
        _fingerprint_key(security_key),
    )

    def _async_handle_advertisement(service_info: Any, _change: Any) -> None:
        _process_advertisement(hass, entry, service_info)

    entry.async_on_unload(
        async_register_callback(
            hass,
            _async_handle_advertisement,
            # Only this switch's advertisements. Switches only broadcast, so also accept
            # advertisements from passive (non-connectable) scanners and proxies.
            {
                "address": str(mac_address).upper(),
                "manufacturer_id": ENOCEAN_MANUFACTURER_ID,
                "connectable": False,
            },
            BluetoothScanningMode.PASSIVE,
        )
    )
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    _LOGGER.info("EnOcean BLE device configured: %s", mac_address)
    return True


def _sequence_store(hass: Any, entry: Any) -> Any:
    """Return the store holding the last accepted sequence counter of an entry."""
    from homeassistant.helpers.storage import Store

    return Store(hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}")


def _sequence_data(entry_data: dict[str, Any]) -> dict[str, int]:
    return {"last_sequence_counter": int(entry_data["last_sequence_counter"])}


def _schedule_sequence_save(entry_data: dict[str, Any]) -> None:
    store = entry_data.get("store")
    if store is not None:
        store.async_delay_save(lambda: _sequence_data(entry_data), STORAGE_SAVE_DELAY_SECONDS)


def _receiver_name(hass: Any, source: str | None) -> str | None:
    """Return the name of the Bluetooth adapter or proxy that received an advertisement."""
    if not source:
        return None
    try:
        from homeassistant.components.bluetooth import async_scanner_by_source

        scanner = async_scanner_by_source(hass, source)
    except Exception:  # diagnostic only: never block an event
        scanner = None
    name = getattr(scanner, "name", None)
    return name if isinstance(name, str) and name else source


def _process_advertisement(
    hass: Any,
    entry: Any,
    service_info: Any,
) -> None:
    """Process BLE advertisements and emit Home Assistant button events."""
    entry_data = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if entry_data is None:
        # Entry data is removed on unload before Home Assistant unregisters this callback.
        _LOGGER.debug("adv_ignored entry_id=%s reason=entry_unloaded", entry.entry_id)
        return
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
            _schedule_sequence_save(entry_data)
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

    receiver = _receiver_name(hass, getattr(service_info, "source", None))
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
            receiver=receiver,
        )
    # Updated after emitting: a release checks the previous device-wide counter.
    entry_data["last_sequence_counter"] = parsed.sequence_counter
    _schedule_sequence_save(entry_data)


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
    receiver: str | None = None,
) -> None:
    from homeassistant.helpers.event import async_call_later

    def fire(event_type: str) -> None:
        _fire_event(
            hass=hass, entry=entry, button=button, event_type=event_type,
            sequence_counter=sequence_counter, rssi=rssi, mac_address=mac_address,
            receiver=receiver,
        )

    buttons = entry_data["buttons"]
    if not isinstance(buttons, dict):
        return

    state_any = buttons.setdefault(
        button,
        {
            "pressed_at": None,
            "long_fired": False,
            "last_single_press_seq": None,
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
        state["long_fired"] = False
        _LOGGER.debug(
            "event_press entry_id=%s mac=%s button=%s sequence_counter=%s",
            entry.entry_id,
            mac_address,
            button,
            sequence_counter,
        )
        fire("press")
        if sequence_counter != state.get("last_single_press_seq"):
            state["last_single_press_seq"] = sequence_counter
            fire("single_press")

        def _long_press_timer(_now: object) -> None:
            if state.get("pressed_at") is None:
                return
            state["long_fired"] = True
            state["cancel_long_cb"] = None
            _LOGGER.debug(
                "event_long_press entry_id=%s mac=%s button=%s", entry.entry_id, mac_address, button,
            )
            fire("long_press")

        def _release_timeout_timer(_now: object) -> None:
            if state.get("pressed_at") is None:
                return
            state["pressed_at"] = None
            state["long_fired"] = False
            state["cancel_timeout_cb"] = None
            _LOGGER.debug(
                "event_release_timeout entry_id=%s mac=%s button=%s", entry.entry_id, mac_address, button,
            )
            fire("release_timeout")

        state["cancel_long_cb"] = async_call_later(hass, LONG_PRESS_SECONDS, _long_press_timer)
        state["cancel_timeout_cb"] = async_call_later(hass, RELEASE_TIMEOUT_SECONDS, _release_timeout_timer)
        return

    if event_type == "release":
        if state.get("pressed_at") is not None:
            _cancel_all_timers(state)
            long_fired = bool(state.get("long_fired"))
            state["pressed_at"] = None
            state["long_fired"] = False
            _LOGGER.debug(
                "event_release entry_id=%s mac=%s button=%s sequence_counter=%s long_fired=%s",
                entry.entry_id, mac_address, button, sequence_counter, long_fired,
            )
            fire("release")
            if long_fired:
                fire("long_release")
        else:
            # The sequence counter is shared by all buttons of the switch: the lost
            # press is the telegram just before this release, whatever button was
            # used before.
            old_seq = int(entry_data.get("last_sequence_counter", -1))
            _LOGGER.debug(
                "event_orphan_release entry_id=%s mac=%s button=%s sequence_counter=%s old_seq=%s",
                entry.entry_id, mac_address, button, sequence_counter, old_seq,
            )
            fire("orphan_release")
            is_coherent = old_seq >= 0 and sequence_counter - old_seq == 2
            if is_coherent and sequence_counter != state.get("last_single_press_seq"):
                state["last_single_press_seq"] = sequence_counter
                fire("single_press")
        return

    fire(event_type)


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
    receiver: str | None = None,
) -> None:
    from homeassistant.helpers.dispatcher import async_dispatcher_send

    signal = SIGNAL_BUTTON_EVENT.format(entry_id=entry.entry_id, button=button)

    @callback
    def _async_dispatch() -> None:
        async_dispatcher_send(hass, signal, payload)
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
        ATTR_RECEIVER: receiver,
    }
    _LOGGER.debug(
        "event_emit entry_id=%s mac=%s button=%s event_type=%s sequence_counter=%s rssi=%s receiver=%s signal=%s",
        entry.entry_id,
        mac_address,
        button,
        event_type,
        sequence_counter,
        rssi,
        receiver,
        signal,
    )
    hass.add_job(_async_dispatch)


async def async_unload_entry(hass: Any, entry: Any) -> bool:
    """Unload a config entry."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        entry_data = hass.data[DOMAIN].pop(entry.entry_id, None) or {}
        # Pending long-press/release-timeout timers would otherwise fire into the reloaded entry.
        for state in entry_data.get("buttons", {}).values():
            if isinstance(state, dict):
                _cancel_all_timers(state)
        store = entry_data.get("store")
        if store is not None:
            # Write now rather than after the save delay, so a reload loads the latest counter.
            await store.async_save(_sequence_data(entry_data))
    _LOGGER.debug("unload_entry entry_id=%s unloaded=%s", entry.entry_id, unloaded)
    return bool(unloaded)


async def async_remove_entry(hass: Any, entry: Any) -> None:
    """Remove the stored sequence counter of a deleted config entry."""
    await _sequence_store(hass, entry).async_remove()


def _fingerprint_key(key_hex: str) -> str:
    """Return a short, non-reversible key fingerprint for debug logs."""
    if not key_hex:
        return "none"
    digest = hashlib.sha256(key_hex.encode("utf-8")).hexdigest()
    return digest[:8]
