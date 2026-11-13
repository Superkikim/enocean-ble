"""Tests for adding a discovered switch from its module label QR code."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.data_entry_flow import FlowResultType, UnknownFlow

from custom_components.enocean_ble import config_flow as config_flow_module
from custom_components.enocean_ble import qr_scan as qr_scan_module
from custom_components.enocean_ble.config_flow import EnOceanBleConfigFlow
from custom_components.enocean_ble.const import (
    CONF_MAC_ADDRESS,
    CONF_SECURITY_KEY,
    DOMAIN,
    ENOCEAN_MANUFACTURER_ID,
)
from custom_components.enocean_ble.qr_scan import _waiting_flow_mac, async_scan_url, device_payloads

# PTM 215B User Manual v2.2, Appendix C.3.1: address, key and a real data telegram.
MAC = "E2:15:00:00:19:B8"
KEY = "3dda31ad44767ae3ce56dce2b3ce2abb"
QR = "30SE215000019B8+Z3DDA31AD44767AE3CE56DCE2B3CE2ABB+30PS3221-A215"
DATA_TELEGRAM = bytes.fromhex("5D04000011B2FA88FF")
OTHER_KEY_QR = "30SE215000019B8+Z00112233445566778899AABBCCDDEEFF+30PS3221-A215"
OTHER_SWITCH_QR = "30SE21500000001+Z3DDA31AD44767AE3CE56DCE2B3CE2ABB+30PS3221-A215"


def _service_info(payload: bytes | None = DATA_TELEGRAM, address: str = MAC) -> SimpleNamespace:
    return SimpleNamespace(
        address=address,
        name=address,
        source="local",
        rssi=-60,
        time=1.0,
        manufacturer_data={ENOCEAN_MANUFACTURER_ID: payload} if payload is not None else {},
    )


async def _discovered_flow(hass: Any, cached: list[SimpleNamespace]) -> tuple[EnOceanBleConfigFlow, Any]:
    """Run the Bluetooth discovery step; ``cached`` is what the bluetooth cache returns."""
    flow = EnOceanBleConfigFlow()
    flow.hass = hass
    flow.handler = DOMAIN
    flow.flow_id = "test-flow"
    flow.context = {"source": "bluetooth"}
    with patch.object(config_flow_module, "async_discovered_service_info", return_value=cached):
        result = await flow.async_step_bluetooth(_service_info())  # type: ignore[arg-type]
    return flow, result


async def test_user_step_requires_discovery(hass: Any) -> None:
    flow = EnOceanBleConfigFlow()
    flow.hass = hass
    result = await flow.async_step_user()
    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "discovery_required"


async def test_discovery_shows_method_menu(hass: Any) -> None:
    _, result = await _discovered_flow(hass, [_service_info()])
    assert result["type"] == FlowResultType.MENU
    assert result["step_id"] == "bluetooth_method"
    assert result["menu_options"] == ["qr_scan", "qr_text", "commissioning"]
    assert result["description_placeholders"]["mac"] == MAC


async def test_qr_text_creates_entry(hass: Any) -> None:
    flow, _ = await _discovered_flow(hass, [_service_info()])
    with patch.object(config_flow_module, "async_discovered_service_info", return_value=[_service_info()]):
        result = await flow.async_step_qr_text({"qr_code": QR})
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["data"] == {CONF_MAC_ADDRESS: MAC, CONF_SECURITY_KEY: KEY}


async def test_qr_text_uses_discovery_payload_when_cache_is_empty(hass: Any) -> None:
    flow, _ = await _discovered_flow(hass, [])
    with patch.object(config_flow_module, "async_discovered_service_info", return_value=[]):
        result = await flow.async_step_qr_text({"qr_code": QR})
    assert result["type"] == FlowResultType.CREATE_ENTRY


@pytest.mark.parametrize(
    ("raw", "error"),
    [
        ("not a qr code", "invalid_qr"),
        (OTHER_SWITCH_QR, "qr_mac_mismatch"),
        (OTHER_KEY_QR, "qr_key_invalid"),
    ],
)
async def test_qr_text_errors(hass: Any, raw: str, error: str) -> None:
    flow, _ = await _discovered_flow(hass, [_service_info()])
    with patch.object(config_flow_module, "async_discovered_service_info", return_value=[_service_info()]):
        result = await flow.async_step_qr_text({"qr_code": raw})
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "qr_text"
    assert result["errors"] == {"base": error}


async def test_qr_text_without_any_telegram(hass: Any) -> None:
    flow, _ = await _discovered_flow(hass, [])
    flow._discovery_payload = None
    with patch.object(config_flow_module, "async_discovered_service_info", return_value=[]):
        result = await flow.async_step_qr_text({"qr_code": QR})
    assert result["errors"] == {"base": "qr_no_telegram"}


async def test_qr_scan_without_https_falls_back_on_text(hass: Any) -> None:
    flow, _ = await _discovered_flow(hass, [_service_info()])
    with (
        patch.object(config_flow_module, "async_setup_scan", AsyncMock()),
        patch.object(config_flow_module, "async_scan_url", return_value=None),
    ):
        result = await flow.async_step_qr_scan()
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "qr_text"
    assert result["errors"] == {"base": "scan_https_required"}


async def test_qr_scan_external_step_then_entry(hass: Any) -> None:
    flow, _ = await _discovered_flow(hass, [_service_info()])
    url = "https://ha.example/api/enocean_ble/qr_scan/test-flow"
    with (
        patch.object(config_flow_module, "async_setup_scan", AsyncMock()),
        patch.object(config_flow_module, "async_scan_url", return_value=url),
    ):
        result = await flow.async_step_qr_scan()
    assert result["type"] == FlowResultType.EXTERNAL_STEP
    assert result["url"] == url

    with patch.object(config_flow_module, "async_discovered_service_info", return_value=[_service_info()]):
        result = await flow.async_step_qr_scan({"qr_code": QR})
    assert result["type"] == FlowResultType.EXTERNAL_STEP_DONE
    assert result["step_id"] == "qr_scan_done"

    # The frontend reloads the step: a confirmation form, as many times as it likes.
    for _ in range(3):
        result = await flow.async_step_qr_scan_done()
        assert result["type"] == FlowResultType.FORM
        assert result["step_id"] == "qr_scan_done"
        assert result["description_placeholders"] == {"name": MAC, "mac": MAC}

    result = await flow.async_step_qr_scan_done({})
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["data"] == {CONF_MAC_ADDRESS: MAC, CONF_SECURITY_KEY: KEY}


async def test_qr_scan_keeps_notifying_until_the_flow_moves_on(hass: Any) -> None:
    """A phone app in the background misses the first notification; repeat it."""
    flow, _ = await _discovered_flow(hass, [_service_info()])
    events: list[Any] = []
    hass.bus.async_listen("data_entry_flow_progressed", events.append)
    with (
        patch.object(config_flow_module, "SCAN_NOTIFY_INTERVAL", 0.01),
        patch.object(config_flow_module, "async_discovered_service_info", return_value=[_service_info()]),
    ):
        flow.cur_step = await flow.async_step_qr_scan({"qr_code": QR})
        await asyncio.sleep(0.05)
        await hass.async_block_till_done()
        assert events
        assert all(event.data["flow_id"] == "test-flow" for event in events)

        # The frontend reloads the flow: the notifications stop at once.
        task = flow._scan_notify_task
        assert task is not None
        result = await flow.async_step_qr_scan_done()
        assert result["type"] == FlowResultType.FORM
        count = len(events)
        await asyncio.sleep(0.05)
        await hass.async_block_till_done()
        assert len(events) == count
    assert task.cancelled()
    assert flow._scan_notify_task is None


async def test_flow_removal_stops_scan_notifications(hass: Any) -> None:
    flow, _ = await _discovered_flow(hass, [_service_info()])
    with patch.object(config_flow_module, "async_discovered_service_info", return_value=[_service_info()]):
        flow.cur_step = await flow.async_step_qr_scan({"qr_code": QR})
    task = flow._scan_notify_task
    assert task is not None
    flow.async_remove()
    await asyncio.sleep(0)
    assert task.cancelled()


async def test_qr_scan_rejected_shows_the_error_then_the_menu(hass: Any) -> None:
    flow, _ = await _discovered_flow(hass, [_service_info()])
    with patch.object(config_flow_module, "async_discovered_service_info", return_value=[_service_info()]):
        result = await flow.async_step_qr_scan({"qr_code": OTHER_SWITCH_QR})
    assert result["type"] == FlowResultType.EXTERNAL_STEP_DONE
    assert result["step_id"] == "qr_scan_error"

    # Reloading the error step keeps showing the error.
    for _ in range(2):
        result = await flow.async_step_qr_scan_error()
        assert result["type"] == FlowResultType.FORM
        assert result["step_id"] == "qr_scan_error"
        assert result["errors"] == {"base": "qr_mac_mismatch"}

    result = await flow.async_step_qr_scan_error({})
    assert result["type"] == FlowResultType.MENU
    assert result["step_id"] == "bluetooth_method"


def test_device_payloads_filters_by_address() -> None:
    infos = [
        _service_info(DATA_TELEGRAM),
        _service_info(b"\x01" * 9, address="E2:15:00:00:00:01"),
        _service_info(None),
    ]
    assert device_payloads(infos, MAC) == [DATA_TELEGRAM]


def _hass_with_flow(flow: dict[str, Any] | None) -> SimpleNamespace:
    def async_get(flow_id: str) -> dict[str, Any]:
        if flow is None:
            raise UnknownFlow
        return flow

    return SimpleNamespace(config_entries=SimpleNamespace(flow=SimpleNamespace(async_get=async_get)))


def test_scan_page_only_serves_a_flow_waiting_on_the_scan_step() -> None:
    waiting = {"handler": DOMAIN, "step_id": "qr_scan", "context": {"unique_id": MAC}}
    assert _waiting_flow_mac(_hass_with_flow(waiting), "f") == MAC
    assert _waiting_flow_mac(_hass_with_flow(None), "f") is None
    assert _waiting_flow_mac(_hass_with_flow({**waiting, "step_id": "qr_text"}), "f") is None
    assert _waiting_flow_mac(_hass_with_flow({**waiting, "handler": "other"}), "f") is None


def test_scan_url_is_unique_on_each_opening() -> None:
    """Opening the scan again must load a new page, not the tab of the last scan."""
    with patch.object(qr_scan_module, "get_url", return_value="https://ha.example"):
        first = async_scan_url(object(), "abc")
        second = async_scan_url(object(), "abc")
    assert first is not None and second is not None
    assert first.startswith("https://ha.example/api/enocean_ble/qr_scan/abc?v=")
    assert second.startswith("https://ha.example/api/enocean_ble/qr_scan/abc?v=")
    assert first != second
