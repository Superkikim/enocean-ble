"""Tests for FLOW_TRACE_V3 termination intent instrumentation."""

from __future__ import annotations

import asyncio
import logging
from types import SimpleNamespace
from typing import Any

from custom_components.enocean_ble.config_flow import EnOceanBleConfigFlow


class _FakeBus:
    """Minimal event bus stub for config flow listener tests."""

    def __init__(self) -> None:
        self._listeners: dict[str, list[Any]] = {}

    def async_listen(self, event_type: str, callback: Any) -> Any:
        listeners = self._listeners.setdefault(event_type, [])
        listeners.append(callback)

        def _unsubscribe() -> None:
            listeners.remove(callback)

        return _unsubscribe

    def fire(self, event_type: str, data: dict[str, Any]) -> None:
        for callback in list(self._listeners.get(event_type, [])):
            callback(SimpleNamespace(data=data))


def _build_flow() -> tuple[EnOceanBleConfigFlow, _FakeBus]:
    flow = EnOceanBleConfigFlow()
    bus = _FakeBus()
    loop = asyncio.get_running_loop()
    flow.hass = SimpleNamespace(loop=loop, bus=bus, async_create_task=loop.create_task)
    flow.flow_id = "flow-trace-v3-test"
    flow._pending_mac = "AA:BB:CC:DD:EE:FF"
    return flow, bus


async def test_abort_explicit_logs_intent_and_terminal_without_entry(caplog: Any) -> None:
    caplog.set_level(logging.DEBUG)
    flow, bus = _build_flow()
    flow._ensure_ui_progress_listener()

    bus.fire(
        "data_entry_flow_progressed",
        {
            "flow_id": flow.flow_id,
            "step_id": "bluetooth_confirm",
            "result": {"type": "abort", "reason": "user_aborted"},
        },
    )
    flow.async_remove()

    text = caplog.text
    assert "event=USER_INTENT_ABORT_EXPLICIT" in text
    assert "event=FLOW_TERMINATED_WITHOUT_ENTRY" in text
    assert "cause=USER_INTENT_ABORT_EXPLICIT" in text


async def test_remove_without_ui_proof_logs_unknown_cause(caplog: Any) -> None:
    caplog.set_level(logging.DEBUG)
    flow, _ = _build_flow()
    flow.async_remove()

    text = caplog.text
    assert "event=TERMINATION_CAUSE_UNKNOWN" in text
    assert "event=FLOW_TERMINATED_WITHOUT_ENTRY" in text
    assert "cause=TERMINATION_CAUSE_UNKNOWN" in text
    assert "event=USER_INTENT_ABORT_EXPLICIT" not in text


async def test_create_entry_nominal_does_not_log_abandon(caplog: Any) -> None:
    caplog.set_level(logging.DEBUG)
    flow, _ = _build_flow()
    flow._entry_created = True
    flow.async_remove()

    text = caplog.text
    assert "event=FLOW_TERMINATED_WITHOUT_ENTRY" not in text
    assert "event=TERMINATION_CAUSE_UNKNOWN" not in text
