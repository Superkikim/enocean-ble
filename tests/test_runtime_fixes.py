"""Advertisement handling, sequence counter persistence and unload (fixes from PR #2 by @lafriks)."""

from __future__ import annotations

import sys
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import homeassistant.components

import custom_components.enocean_ble as integration
from custom_components.enocean_ble.const import (
    CONF_MAC_ADDRESS,
    CONF_SECURITY_KEY,
    DOMAIN,
    ENOCEAN_MANUFACTURER_ID,
)

# PTM 215B User Manual v2.2, Appendix C.3.1: A0 press telegram, sequence counter 0x045D.
MAC = "E2:15:00:00:19:B8"
KEY = "3dda31ad44767ae3ce56dce2b3ce2abb"
TELEGRAM = bytes.fromhex("5D04000011B2FA88FF")
TELEGRAM_SEQ = 0x045D


def _env(last_sequence_counter: int = -1) -> tuple[Any, Any, dict[str, Any]]:
    entry = SimpleNamespace(entry_id="entry", data={CONF_MAC_ADDRESS: MAC, CONF_SECURITY_KEY: KEY})
    entry_data: dict[str, Any] = {
        CONF_MAC_ADDRESS: MAC,
        CONF_SECURITY_KEY: KEY,
        "store": MagicMock(),
        "last_sequence_counter": last_sequence_counter,
        "buttons": {},
    }
    hass = MagicMock()
    hass.data = {DOMAIN: {entry.entry_id: entry_data}}
    return hass, entry, entry_data


def _advertisement(source: str = "14:08:08:54:F2:26") -> SimpleNamespace:
    return SimpleNamespace(
        address=MAC,
        rssi=-70,
        source=source,
        manufacturer_data={ENOCEAN_MANUFACTURER_ID: TELEGRAM},
    )


def _process(hass: Any, entry: Any) -> list[dict[str, Any]]:
    fired: list[dict[str, Any]] = []
    with (
        patch.object(integration, "_fire_event", side_effect=lambda **kw: fired.append(kw)),
        patch("homeassistant.helpers.event.async_call_later", return_value=MagicMock()),
        patch.object(integration, "_receiver_name", return_value="atom-lite-bt-proxy"),
    ):
        integration._process_advertisement(hass, entry, _advertisement())
    return fired


def test_new_telegram_is_emitted_with_its_receiver_and_counter_saved() -> None:
    hass, entry, entry_data = _env()
    fired = _process(hass, entry)
    assert [kw["event_type"] for kw in fired] == ["press", "single_press"]
    assert all(kw["receiver"] == "atom-lite-bt-proxy" for kw in fired)
    assert entry_data["last_sequence_counter"] == TELEGRAM_SEQ
    entry_data["store"].async_delay_save.assert_called_once()


def test_cached_telegram_replayed_after_restart_is_ignored() -> None:
    """At startup Home Assistant replays its cached advertisement: the stored counter rejects it."""
    hass, entry, _ = _env(last_sequence_counter=TELEGRAM_SEQ)
    assert _process(hass, entry) == []


def test_advertisement_after_unload_is_ignored() -> None:
    hass, entry, _ = _env()
    hass.data = {DOMAIN: {}}
    assert _process(hass, entry) == []


def test_receiver_name_uses_the_scanner_name() -> None:
    scanner = SimpleNamespace(name="atom-lite-bt-proxy (14:08:08:54:F2:26)")
    with patch("homeassistant.components.bluetooth.async_scanner_by_source", return_value=scanner):
        assert integration._receiver_name(MagicMock(), "14:08:08:54:F2:26") == scanner.name
    with patch("homeassistant.components.bluetooth.async_scanner_by_source", return_value=None):
        assert integration._receiver_name(MagicMock(), "14:08:08:54:F2:26") == "14:08:08:54:F2:26"
    assert integration._receiver_name(MagicMock(), None) is None


async def test_unload_cancels_timers_and_saves_the_counter() -> None:
    hass, entry, entry_data = _env(last_sequence_counter=42)
    hass.config_entries.async_unload_platforms = AsyncMock(return_value=True)
    store = MagicMock()
    store.async_save = AsyncMock()
    entry_data["store"] = store
    cancel_long, cancel_timeout = MagicMock(), MagicMock()
    entry_data["buttons"] = {"A0": {"cancel_long_cb": cancel_long, "cancel_timeout_cb": cancel_timeout}}

    assert await integration.async_unload_entry(hass, entry) is True
    cancel_long.assert_called_once()
    cancel_timeout.assert_called_once()
    store.async_save.assert_awaited_once_with({"last_sequence_counter": 42})
    assert entry.entry_id not in hass.data[DOMAIN]


async def test_failed_unload_keeps_the_entry_data() -> None:
    hass, entry, _ = _env()
    hass.config_entries.async_unload_platforms = AsyncMock(return_value=False)
    assert await integration.async_unload_entry(hass, entry) is False
    assert entry.entry_id in hass.data[DOMAIN]


async def test_removing_the_entry_removes_its_stored_counter() -> None:
    store = MagicMock()
    store.async_remove = AsyncMock()
    with patch.object(integration, "_sequence_store", return_value=store):
        await integration.async_remove_entry(MagicMock(), SimpleNamespace(entry_id="entry"))
    store.async_remove.assert_awaited_once()


def test_duplicate_telegram_is_dropped_before_the_aes_check() -> None:
    """Each telegram arrives once per repetition and per receiver: copies skip the MIC check."""
    hass, entry, _ = _env(last_sequence_counter=TELEGRAM_SEQ)
    with patch.object(integration, "parse_data_telegram") as parse:
        assert _process(hass, entry) == []
    parse.assert_not_called()


async def _setup(register_every: Any) -> tuple[Any, Any]:
    hass = MagicMock()
    hass.data = {}
    hass.config_entries.async_forward_entry_setups = AsyncMock()
    entry = MagicMock()
    entry.entry_id = "entry"
    entry.data = {CONF_MAC_ADDRESS: MAC.lower(), CONF_SECURITY_KEY: KEY}
    store = MagicMock()
    store.async_load = AsyncMock(return_value={"last_sequence_counter": 7})
    bluetooth = MagicMock()
    if register_every is None:
        del bluetooth.async_register_advertisement_callback
    else:
        bluetooth.async_register_advertisement_callback = register_every
    with (
        patch.object(integration, "_sequence_store", return_value=store),
        patch.dict(sys.modules, {"homeassistant.components.bluetooth": bluetooth}),
        patch.object(homeassistant.components, "bluetooth", bluetooth, create=True),
    ):
        assert await integration.async_setup_entry(hass, entry) is True
    assert hass.data[DOMAIN]["entry"]["last_sequence_counter"] == 7
    return bluetooth, hass


async def test_setup_listens_to_every_receiver_when_available() -> None:
    register_every = MagicMock()
    bluetooth, hass = await _setup(register_every)
    register_every.assert_called_once()
    assert register_every.call_args.args[0] is hass
    assert register_every.call_args.args[2] == MAC
    bluetooth.async_register_callback.assert_not_called()


async def test_setup_falls_back_on_the_owner_receiver_before_2026_10() -> None:
    bluetooth, _ = await _setup(None)
    bluetooth.async_register_callback.assert_called_once()
    matcher = bluetooth.async_register_callback.call_args.args[2]
    assert matcher == {"address": MAC, "manufacturer_id": ENOCEAN_MANUFACTURER_ID, "connectable": False}
