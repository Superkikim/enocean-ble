"""Button modes: Simple, Short + long and Short + hold never fire two actions for one gesture."""

from __future__ import annotations

from contextlib import ExitStack
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.data_entry_flow import FlowResultType

import custom_components.enocean_ble as integration
from custom_components.enocean_ble import button_mode
from custom_components.enocean_ble.config_flow import EnOceanBleOptionsFlow
from custom_components.enocean_ble.const import (
    CONF_BUTTON_MODE,
    DOMAIN,
    GESTURE_THRESHOLD_SECONDS,
    MODE_EVENT_TYPES,
    RAW_EVENT_TYPES,
    RELEASE_TIMEOUT_SECONDS,
)
from custom_components.enocean_ble.event import (
    BUTTONS,
    EnOceanBleButtonEventEntity,
    EnOceanBleRawEventEntity,
)
from custom_components.enocean_ble.repairs import LegacyButtonModeRepairFlow


class Switch:
    """Feed telegrams of one switch through the mode logic, with a fake clock and timers."""

    def __init__(self, mode: str) -> None:
        self.now = 100.0
        self.seq = 10
        self.events: list[tuple[str, str, dict[str, Any]]] = []
        self.timers: dict[int, tuple[float, Any]] = {}
        self._next_timer = 0
        self.entry = SimpleNamespace(entry_id="entry")
        self.entry_data: dict[str, Any] = {"buttons": {}, "mode": mode, "last_sequence_counter": self.seq}

    def _call_later(self, _hass: Any, delay: float, callback: Any) -> Any:
        timer_id = self._next_timer
        self._next_timer += 1
        self.timers[timer_id] = (self.now + delay, callback)
        return lambda: self.timers.pop(timer_id, None)

    def _record(self, **kw: Any) -> None:
        self.events.append((kw["button"], kw["event_type"], kw.get("extra") or {}))

    def _patched(self) -> Any:
        stack = ExitStack()
        stack.enter_context(patch("homeassistant.helpers.event.async_call_later", side_effect=self._call_later))
        stack.enter_context(patch.object(integration, "_fire_event", side_effect=self._record))
        stack.enter_context(patch.object(integration, "monotonic", side_effect=lambda: self.now))
        return stack

    def wait(self, seconds: float) -> None:
        """Advance the clock and run the timers that are due."""
        self.now += seconds
        with self._patched():
            for timer_id, (due, callback) in sorted(self.timers.items(), key=lambda item: item[1][0]):
                if due <= self.now and timer_id in self.timers:
                    del self.timers[timer_id]
                    callback(None)

    def telegram(self, event_type: str, button: str = "A0", *, lost_before: int = 0) -> None:
        """Receive the next telegram; ``lost_before`` telegrams before it were lost."""
        self.seq += 1 + lost_before
        with self._patched():
            integration._emit_button_event(
                hass=MagicMock(),
                entry=self.entry,
                entry_data=self.entry_data,
                button=button,
                event_type=event_type,
                sequence_counter=self.seq,
                rssi=-60,
                mac_address="E2:15:00:00:19:B8",
            )
        self.entry_data["last_sequence_counter"] = self.seq

    def click(self, button: str = "A0", held: float = 0.2) -> None:
        self.telegram("press", button)
        self.wait(held)
        self.telegram("release", button)

    def names(self) -> list[str]:
        return [name for _, name, _ in self.events]


# --- Simple -----------------------------------------------------------------------


def test_simple_fires_on_press_only() -> None:
    switch = Switch("simple")
    switch.click(held=3.0)
    assert switch.names() == ["single_press"]


def test_simple_recovers_a_lost_press_on_its_release() -> None:
    switch = Switch("simple")
    switch.telegram("release", lost_before=1)
    assert switch.names() == ["single_press"]


def test_simple_ignores_a_release_after_several_lost_telegrams() -> None:
    switch = Switch("simple")
    switch.telegram("release", lost_before=3)
    assert switch.names() == []


# --- Short + long -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("held", "expected"),
    [(0.3, "short_press"), (GESTURE_THRESHOLD_SECONDS - 0.01, "short_press"), (GESTURE_THRESHOLD_SECONDS, "long_press"), (5.0, "long_press"), (20.0, "long_press")],
)
def test_short_long_decides_on_the_release(held: float, expected: str) -> None:
    switch = Switch("short_long")
    switch.telegram("press")
    switch.wait(held)
    assert switch.names() == []  # nothing before the release
    switch.telegram("release")
    assert switch.names() == [expected]


def test_short_long_lost_release_loses_the_action_only() -> None:
    switch = Switch("short_long")
    switch.telegram("press")
    switch.wait(3.0)
    switch.click()  # the release of the first click was lost
    assert switch.names() == ["short_press"]


def test_short_long_lost_press_triggers_nothing() -> None:
    switch = Switch("short_long")
    switch.telegram("release", lost_before=1)
    assert switch.names() == []


# --- Short + hold -------------------------------------------------------------------


def test_short_hold_short_press() -> None:
    switch = Switch("short_hold")
    switch.click(held=0.4)
    switch.wait(10)
    assert switch.names() == ["short_press"]
    assert switch.timers == {}


def test_short_hold_hold_then_release() -> None:
    switch = Switch("short_hold")
    switch.telegram("press")
    switch.wait(GESTURE_THRESHOLD_SECONDS)
    assert switch.names() == ["hold_press"]
    switch.wait(2.0)
    switch.telegram("release")
    switch.wait(10)
    assert switch.events[-1] == ("A0", "hold_release", {"reason": "release"})
    assert switch.names() == ["hold_press", "hold_release"]


def test_short_hold_lost_release_ends_after_the_safety_timeout() -> None:
    switch = Switch("short_hold")
    switch.telegram("press")
    switch.wait(RELEASE_TIMEOUT_SECONDS)
    assert switch.events[-1] == ("A0", "hold_release", {"reason": "timeout"})
    # The real release, if it arrives later, is ignored.
    switch.telegram("release")
    assert switch.names() == ["hold_press", "hold_release"]


def test_short_hold_press_that_stops_a_phantom_hold_is_swallowed() -> None:
    switch = Switch("short_hold")
    switch.click(held=0.3)
    switch.events.clear()
    switch.telegram("press")  # its release is lost: a phantom hold starts
    switch.wait(GESTURE_THRESHOLD_SECONDS + 1)
    switch.click()  # the user presses again to stop it
    assert switch.names() == ["hold_press", "hold_release"]
    assert switch.events[-1][2] == {"reason": "next_telegram"}
    switch.click()  # the next click works normally
    assert switch.names()[-1] == "short_press"


def test_short_hold_other_button_ends_the_hold_and_still_acts() -> None:
    switch = Switch("short_hold")
    switch.telegram("press", "B0")
    switch.wait(GESTURE_THRESHOLD_SECONDS + 0.5)
    switch.click("A0")
    assert switch.events == [
        ("B0", "hold_press", {}),
        ("B0", "hold_release", {"reason": "next_telegram"}),
        ("A0", "short_press", {}),
    ]


def test_short_hold_pending_press_lost_release_does_not_become_a_hold() -> None:
    switch = Switch("short_hold")
    switch.telegram("press", "B0")  # its release is lost
    switch.wait(0.3)
    switch.click("A0")
    switch.wait(10)
    assert switch.events == [("A0", "short_press", {})]


def test_short_hold_lost_press_triggers_nothing() -> None:
    switch = Switch("short_hold")
    switch.telegram("release", lost_before=1)
    assert switch.names() == []


# --- Raw events, diagnostics ----------------------------------------------------------

MAC = "E2:15:00:00:19:B8"
KEY = "3dda31ad44767ae3ce56dce2b3ce2abb"
TELEGRAM = bytes.fromhex("5D04000011B2FA88FF")  # A0 press, sequence counter 0x045D


def _process(last_sequence_counter: int, mode: str = "simple") -> tuple[list[dict[str, Any]], dict[str, Any]]:
    entry = SimpleNamespace(entry_id="entry", data={})
    entry_data: dict[str, Any] = {
        "mac_address": MAC,
        "security_key": KEY,
        "store": MagicMock(),
        "last_sequence_counter": last_sequence_counter,
        "buttons": {},
        "mode": mode,
        "lost_messages": 0,
    }
    hass = MagicMock()
    hass.data = {DOMAIN: {"entry": entry_data}}
    fired: list[dict[str, Any]] = []
    info = SimpleNamespace(address=MAC, rssi=-71, source="aa", manufacturer_data={0x03DA: TELEGRAM})
    with (
        patch.object(integration, "_fire_event", side_effect=lambda **kw: fired.append(kw)),
        patch.object(integration, "_receiver_name", return_value="proxy"),
        patch("homeassistant.helpers.dispatcher.async_dispatcher_send") as send,
    ):
        integration._process_advertisement(hass, entry, info)
    send.assert_called_with(hass, "enocean_ble_device_update_entry")
    return fired, entry_data


def test_raw_press_is_fired_in_every_mode_before_the_action() -> None:
    fired, entry_data = _process(0x045C)
    assert [kw["event_type"] for kw in fired] == ["raw_press", "single_press"]
    assert entry_data["last_rssi"] == -71
    assert entry_data["last_receiver"] == "proxy"
    assert entry_data["last_seen"] is not None
    assert entry_data["lost_messages"] == 0


def test_lost_messages_count_the_gaps_of_the_sequence_counter() -> None:
    _, entry_data = _process(0x045D - 4)
    assert entry_data["lost_messages"] == 3


def test_large_gaps_are_not_counted_as_lost() -> None:
    """Home Assistant was off, or the switch was used elsewhere."""
    _, entry_data = _process(0x045D - 500)
    assert entry_data["lost_messages"] == 0


# --- Entities, options, repair ---------------------------------------------------------


def test_button_mode_of_switches_added_before_2026_11_is_legacy() -> None:
    assert button_mode(SimpleNamespace(options={})) == "legacy"
    assert button_mode(SimpleNamespace(options={CONF_BUTTON_MODE: "short_hold"})) == "short_hold"
    assert button_mode(SimpleNamespace(options={CONF_BUTTON_MODE: "unknown"})) == "legacy"
    assert button_mode(SimpleNamespace(options={CONF_BUTTON_MODE: "legacy"})) == "legacy"


@pytest.mark.parametrize("mode", ["simple", "short_long", "short_hold", "legacy"])
def test_button_entities_declare_only_the_events_of_their_mode(mode: str) -> None:
    entry = SimpleNamespace(entry_id="entry", unique_id="E2:15:00:00:19:B8", options={CONF_BUTTON_MODE: mode}, data={}, title="Sud Top")
    entity = EnOceanBleButtonEventEntity(entry, BUTTONS[0], MODE_EVENT_TYPES[mode])  # type: ignore[arg-type]
    raw = EnOceanBleRawEventEntity(entry, BUTTONS[0])  # type: ignore[arg-type]
    assert entity.event_types == MODE_EVENT_TYPES[mode]
    assert entity.unique_id == "E2:15:00:00:19:B8_a0"
    assert raw.event_types == RAW_EVENT_TYPES
    assert raw.unique_id == "E2:15:00:00:19:B8_a0_raw"
    assert raw.entity_registry_enabled_default is False

    triggered: list[tuple[str, dict[str, Any]]] = []
    with (
        patch.object(entity, "_trigger_event", side_effect=lambda name, data: triggered.append((name, data))),
        patch.object(entity, "async_write_ha_state"),
    ):
        entity._async_handle_button_event({"event_type": "raw_press"})
        entity._async_handle_button_event({"event_type": MODE_EVENT_TYPES[mode][0], "reason": "release"})
    assert [name for name, _ in triggered] == [MODE_EVENT_TYPES[mode][0]]
    assert triggered[0][1]["reason"] == "release"


def _schema_fields(result: Any) -> dict[Any, Any]:
    schema = result["data_schema"]
    assert schema is not None
    fields: dict[Any, Any] = schema.schema
    return fields


async def _options_form(mode: str | None) -> Any:
    flow = EnOceanBleOptionsFlow()
    options = {CONF_BUTTON_MODE: mode} if mode else {}
    with patch.object(type(flow), "config_entry", SimpleNamespace(options=options)):
        return await flow.async_step_init(), flow


async def test_options_list_legacy_only_while_the_switch_uses_it() -> None:
    result, _ = await _options_form(None)
    options = _schema_fields(result)
    selector = next(iter(options.values()))
    assert selector.config["options"] == ["simple", "short_long", "short_hold", "legacy"]
    result, _ = await _options_form("short_long")
    selector = next(iter(_schema_fields(result).values()))
    assert selector.config["options"] == ["simple", "short_long", "short_hold"]


async def test_options_save_the_new_mode() -> None:
    flow = EnOceanBleOptionsFlow()
    with patch.object(type(flow), "config_entry", SimpleNamespace(options={CONF_BUTTON_MODE: "simple"})):
        result = await flow.async_step_init({CONF_BUTTON_MODE: "short_hold"})
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["data"] == {CONF_BUTTON_MODE: "short_hold"}


async def test_repair_sets_the_chosen_mode() -> None:
    entry = SimpleNamespace(entry_id="entry", title="Sud Top", options={})
    hass = MagicMock()
    hass.config_entries.async_get_entry.return_value = entry
    flow = LegacyButtonModeRepairFlow("entry")
    flow.hass = hass
    # Home Assistant opens the repair with the issue data as "user input".
    with patch("custom_components.enocean_ble.repairs.find_switch_users", return_value=[]):
        result = await flow.async_step_init({"entry_id": "entry"})
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "confirm"
    assert result["description_placeholders"] == {"name": "Sud Top", "usage": "—"}
    selector = next(iter(_schema_fields(result).values()))
    assert selector.config["options"] == ["simple", "short_long", "short_hold", "legacy"]
    assert selector.config["translation_key"] == "button_mode_repair"
    assert next(iter(_schema_fields(result))).default() == "legacy"
    result = await flow.async_step_confirm({CONF_BUTTON_MODE: "short_long"})
    assert result["type"] == FlowResultType.CREATE_ENTRY
    hass.config_entries.async_update_entry.assert_called_once_with(
        entry, options={CONF_BUTTON_MODE: "short_long"}
    )


async def test_repair_of_a_removed_switch_aborts() -> None:
    hass = MagicMock()
    hass.config_entries.async_get_entry.return_value = None
    flow = LegacyButtonModeRepairFlow("gone")
    flow.hass = hass
    result = await flow.async_step_init()
    assert result["type"] == FlowResultType.ABORT


async def test_switch_reloads_only_when_its_mode_changes() -> None:
    hass = MagicMock()
    hass.config_entries.async_reload = AsyncMock()
    hass.data = {DOMAIN: {"entry": {"mode": "simple"}}}
    entry = SimpleNamespace(entry_id="entry", options={CONF_BUTTON_MODE: "simple"})
    await integration._async_entry_updated(hass, entry)
    hass.config_entries.async_reload.assert_not_called()
    entry.options = {CONF_BUTTON_MODE: "short_hold"}
    await integration._async_entry_updated(hass, entry)
    hass.config_entries.async_reload.assert_awaited_once_with("entry")


def test_legacy_chosen_on_purpose_has_no_repair_issue() -> None:
    entry = SimpleNamespace(entry_id="entry", title="Sud Top", options={CONF_BUTTON_MODE: "legacy"})
    with patch("homeassistant.helpers.issue_registry.async_create_issue") as create:
        integration._async_update_legacy_issue(MagicMock(), entry, "legacy")
    create.assert_not_called()


def test_legacy_switch_gets_a_repair_issue_and_new_modes_remove_it() -> None:
    entry = SimpleNamespace(entry_id="entry", title="Sud Top", options={})
    with (
        patch("homeassistant.helpers.issue_registry.async_create_issue") as create,
        patch("homeassistant.helpers.issue_registry.async_delete_issue") as delete,
    ):
        integration._async_update_legacy_issue(MagicMock(), entry, "legacy")
        integration._async_update_legacy_issue(MagicMock(), entry, "simple")
    assert create.call_args.args[1:] == (DOMAIN, "legacy_button_mode_entry")
    assert create.call_args.kwargs["is_fixable"] is True
    assert create.call_args.kwargs["translation_placeholders"] == {"name": "Sud Top"}
    assert delete.call_args.args[1:] == (DOMAIN, "legacy_button_mode_entry")


# --- Automations and scripts that use a switch -----------------------------------------


def _component(*items: SimpleNamespace) -> SimpleNamespace:
    return SimpleNamespace(entities=list(items))


def _item(entity_id: str, name: str, **kwargs: Any) -> SimpleNamespace:
    values: dict[str, Any] = {
        "entity_id": entity_id,
        "name": name,
        "referenced_entities": set(),
        "referenced_devices": set(),
        "raw_config": {},
    }
    values.update(kwargs)
    return SimpleNamespace(**values)


def _find_users(automations: list[SimpleNamespace], scripts: list[SimpleNamespace]) -> list[str]:
    from custom_components.enocean_ble import usage

    registry_entries = [
        SimpleNamespace(
            entity_id="sensor.sud_top_a0_event", domain="sensor", unique_id="mac_a0_event", device_id="dev"
        ),
        SimpleNamespace(entity_id="event.sud_top_a0", domain="event", unique_id="mac_a0", device_id="dev"),
    ]
    hass = SimpleNamespace(data={"automation": _component(*automations), "script": _component(*scripts)})
    entry = SimpleNamespace(entry_id="entry")
    with (
        patch.object(usage.er, "async_get", return_value=MagicMock()),
        patch.object(usage.er, "async_entries_for_config_entry", return_value=registry_entries),
    ):
        return usage.find_switch_users(hass, entry)  # type: ignore[arg-type]


def test_users_found_by_reference_device_and_template_text() -> None:
    users = _find_users(
        [
            _item("automation.structured", "Structured", referenced_entities={"sensor.sud_top_a0_event"}),
            _item("automation.by_device", "By device", referenced_devices={"dev"}),
            _item(
                "automation.template",
                "Template",
                raw_config={"actions": [{"if": "{{ states('sensor.sud_top_a0_event') }}"}]},
            ),
            _item(
                "automation.integration",
                "Integration",
                raw_config={"v": "{{ integration_entities('enocean_ble') }}"},
            ),
            _item("automation.other", "Other", referenced_entities={"light.kitchen"}),
        ],
        [_item("script.uses_it", "Uses it", referenced_entities={"sensor.sud_top_a0_event"})],
    )
    assert users == [
        "- By device (`automation.by_device`)",
        "- Integration (`automation.integration`)",
        "- Structured (`automation.structured`)",
        "- Template (`automation.template`)",
        "- Uses it (`script.uses_it`)",
    ]


def test_no_users_found() -> None:
    assert _find_users([_item("automation.other", "Other")], []) == []


def test_users_search_survives_a_missing_component() -> None:
    from custom_components.enocean_ble import usage

    hass = SimpleNamespace(data={})
    with (
        patch.object(usage.er, "async_get", return_value=MagicMock()),
        patch.object(usage.er, "async_entries_for_config_entry", return_value=[]),
    ):
        assert usage.find_switch_users(hass, SimpleNamespace(entry_id="e")) == []  # type: ignore[arg-type]
