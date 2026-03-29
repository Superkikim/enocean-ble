"""Tests for FLOW_TRACE_V3 termination intent instrumentation."""

from __future__ import annotations

import logging
from types import SimpleNamespace
from typing import Any

from custom_components.enocean_ble.config_flow import EnOceanBleConfigFlow


def _build_flow() -> EnOceanBleConfigFlow:
    flow = EnOceanBleConfigFlow()
    loop = SimpleNamespace(time=lambda: 0.0)
    flow.hass = SimpleNamespace(loop=loop)
    flow.flow_id = "flow-trace-v3-test"
    flow._pending_mac = "AA:BB:CC:DD:EE:FF"
    return flow


async def test_remove_without_entry_logs_terminal_without_entry(caplog: Any) -> None:
    caplog.set_level(logging.DEBUG)
    flow = _build_flow()
    flow.async_remove()

    text = caplog.text
    assert "event=FLOW_TERMINATED_WITHOUT_ENTRY" in text
    assert "cause=UNKNOWN" in text


async def test_remove_without_ui_proof_logs_unknown_cause(caplog: Any) -> None:
    caplog.set_level(logging.DEBUG)
    flow = _build_flow()
    flow.async_remove()

    text = caplog.text
    assert "event=FLOW_TERMINATED_WITHOUT_ENTRY" in text
    assert "cause=UNKNOWN" in text
    assert "event=USER_INTENT_ABORT_EXPLICIT" not in text


async def test_create_entry_nominal_does_not_log_abandon(caplog: Any) -> None:
    caplog.set_level(logging.DEBUG)
    flow = _build_flow()
    flow._entry_created = True
    flow.async_remove()

    text = caplog.text
    assert "event=FLOW_TERMINATED_WITHOUT_ENTRY" not in text
