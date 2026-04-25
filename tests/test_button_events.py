"""Tests for button event state machine in __init__.py."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from custom_components.enocean_ble import _emit_button_event
from custom_components.enocean_ble.const import (
    LONG_PRESS_SECONDS,
    LONG_PRESS_WATCHDOG_SECONDS,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_env():
    """Return (hass, entry, entry_data, pending_timers, fake_call_later).

    pending_timers maps timer_id -> (delay, callback, cancel_mock).
    Calling cancel_mock() removes the entry, simulating HA cancellation.
    Firing a timer manually should be followed by del pending[tid] to simulate
    HA removing the timer from its registry after it fires.
    """
    pending: dict[int, tuple] = {}
    _id = [0]

    def fake_call_later(_hass, delay, cb):
        tid = _id[0]
        _id[0] += 1
        cancel = MagicMock(name=f"cancel_{tid}")
        pending[tid] = (delay, cb, cancel)
        cancel.side_effect = lambda: pending.pop(tid, None)
        return cancel

    hass = MagicMock()
    entry = SimpleNamespace(entry_id="test")
    entry_data: dict = {"buttons": {}}
    return hass, entry, entry_data, pending, fake_call_later


_COMMON = dict(button="A0", sequence_counter=1, rssi=-70, mac_address="E2:15:00:03:C6:D7")


def _emit(hass, entry, entry_data, event_type, events, fake_call_later, seq=None):
    """Emit one button event, capturing fired event_types into events list."""
    kwargs = dict(_COMMON)
    if seq is not None:
        kwargs["sequence_counter"] = seq
    with (
        patch("homeassistant.helpers.event.async_call_later", side_effect=fake_call_later),
        patch("custom_components.enocean_ble._fire_event", side_effect=lambda **kw: events.append(kw["event_type"])),
    ):
        _emit_button_event(hass=hass, entry=entry, entry_data=entry_data, event_type=event_type, **kwargs)


def _fire_pending(pending: dict, delay: float, events: list, fake_call_later):
    """Fire the pending timer with the given delay, then remove it (simulating HA behavior)."""
    target = next(
        (tid, cb) for tid, (d, cb, _) in pending.items() if d == delay
    )
    tid, cb = target
    del pending[tid]
    with (
        patch("homeassistant.helpers.event.async_call_later", side_effect=fake_call_later),
        patch("custom_components.enocean_ble._fire_event", side_effect=lambda **kw: events.append(kw["event_type"])),
    ):
        cb(None)


# ---------------------------------------------------------------------------
# Short press
# ---------------------------------------------------------------------------

class TestShortPress:
    def test_press_then_release_emits_press_release(self):
        hass, entry, entry_data, pending, fake_call_later = _make_env()
        events = []

        _emit(hass, entry, entry_data, "press", events, fake_call_later)
        assert events == ["press"]
        assert len(pending) == 1  # long_press timer scheduled

        _emit(hass, entry, entry_data, "release", events, fake_call_later)
        assert events == ["press", "release"]
        assert len(pending) == 0  # long_press timer cancelled

    def test_release_without_prior_press_is_harmless(self):
        hass, entry, entry_data, pending, fake_call_later = _make_env()
        events = []

        _emit(hass, entry, entry_data, "release", events, fake_call_later)
        assert events == ["release"]
        assert len(pending) == 0


# ---------------------------------------------------------------------------
# Long press — normal (release arrives before watchdog)
# ---------------------------------------------------------------------------

class TestLongPressNormal:
    def test_long_press_fires_long_press_and_schedules_watchdog(self):
        hass, entry, entry_data, pending, fake_call_later = _make_env()
        events = []

        _emit(hass, entry, entry_data, "press", events, fake_call_later)
        assert len(pending) == 1

        _fire_pending(pending, LONG_PRESS_SECONDS, events, fake_call_later)

        assert events == ["press", "long_press"]
        assert len(pending) == 1  # watchdog timer scheduled
        delay, _, _ = next(iter(pending.values()))
        assert delay == LONG_PRESS_WATCHDOG_SECONDS

    def test_release_after_long_press_emits_long_release_cancels_watchdog(self):
        hass, entry, entry_data, pending, fake_call_later = _make_env()
        events = []

        _emit(hass, entry, entry_data, "press", events, fake_call_later)
        _fire_pending(pending, LONG_PRESS_SECONDS, events, fake_call_later)
        assert events == ["press", "long_press"]
        assert len(pending) == 1  # watchdog pending

        _emit(hass, entry, entry_data, "release", events, fake_call_later)

        assert events == ["press", "long_press", "long_release"]
        assert len(pending) == 0  # watchdog cancelled


# ---------------------------------------------------------------------------
# Long press — lost release (watchdog fires)
# ---------------------------------------------------------------------------

class TestLongPressWatchdog:
    def test_watchdog_fires_synthetic_long_release_when_release_lost(self):
        hass, entry, entry_data, pending, fake_call_later = _make_env()
        events = []

        _emit(hass, entry, entry_data, "press", events, fake_call_later)
        _fire_pending(pending, LONG_PRESS_SECONDS, events, fake_call_later)
        assert events == ["press", "long_press"]
        assert len(pending) == 1  # watchdog pending

        # Release never arrives — watchdog fires
        _fire_pending(pending, LONG_PRESS_WATCHDOG_SECONDS, events, fake_call_later)

        assert events == ["press", "long_press", "long_release"]
        assert len(pending) == 0

    def test_new_press_after_lost_release_cancels_watchdog(self):
        hass, entry, entry_data, pending, fake_call_later = _make_env()
        events = []

        _emit(hass, entry, entry_data, "press", events, fake_call_later)
        _fire_pending(pending, LONG_PRESS_SECONDS, events, fake_call_later)
        assert len(pending) == 1  # watchdog pending

        # New press arrives while watchdog is pending (release still lost)
        _emit(hass, entry, entry_data, "press", events, fake_call_later, seq=2)

        assert events[-1] == "press"
        assert len(pending) == 1  # only new long_press timer; watchdog was cancelled

    def test_watchdog_is_noop_if_release_already_processed(self):
        """If watchdog fires after release was already received, it must do nothing."""
        hass, entry, entry_data, pending, fake_call_later = _make_env()
        events = []

        _emit(hass, entry, entry_data, "press", events, fake_call_later)
        _fire_pending(pending, LONG_PRESS_SECONDS, events, fake_call_later)

        # Release arrives and cancels watchdog
        _emit(hass, entry, entry_data, "release", events, fake_call_later)
        assert events == ["press", "long_press", "long_release"]

        # State must be fully reset — pressed_at=None, long_fired=False
        state = entry_data["buttons"]["A0"]
        assert state["pressed_at"] is None
        assert not state["long_fired"]
