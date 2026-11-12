"""Tests for button event state machine in __init__.py."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

from custom_components.enocean_ble import _emit_button_event
from custom_components.enocean_ble.const import (
    LONG_PRESS_SECONDS,
    RELEASE_TIMEOUT_SECONDS,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_BUTTON = "A0"
_SEQ = 1
_RSSI = -70
_MAC = "E2:15:00:03:C6:D7"


def _make_env() -> tuple[Any, Any, dict[str, Any], dict[int, tuple[float, Any, MagicMock]], Any]:
    """Return (hass, entry, entry_data, pending_timers, fake_call_later).

    pending_timers maps timer_id -> (delay, callback, cancel_mock).
    Calling cancel_mock() removes the entry, simulating HA cancellation.
    Firing a timer manually should be followed by del pending[tid] to simulate
    HA removing the timer from its registry after it fires.
    """
    pending: dict[int, tuple[float, Any, MagicMock]] = {}
    _id = [0]

    def fake_call_later(_hass: Any, delay: float, cb: Any) -> MagicMock:
        tid = _id[0]
        _id[0] += 1
        cancel: MagicMock = MagicMock(name=f"cancel_{tid}")
        pending[tid] = (delay, cb, cancel)
        cancel.side_effect = lambda: pending.pop(tid, None)
        return cancel

    hass = MagicMock()
    entry = SimpleNamespace(entry_id="test")
    entry_data: dict[str, Any] = {"buttons": {}}
    return hass, entry, entry_data, pending, fake_call_later


def _emit(
    hass: Any,
    entry: Any,
    entry_data: dict[str, Any],
    event_type: str,
    events: list[str],
    fake_call_later: Any,
    seq: int | None = None,
) -> None:
    """Emit one button event, capturing fired event_types into events list."""
    seq_val: int = seq if seq is not None else _SEQ
    with (
        patch("homeassistant.helpers.event.async_call_later", side_effect=fake_call_later),
        patch("custom_components.enocean_ble._fire_event", side_effect=lambda **kw: events.append(kw["event_type"])),
    ):
        _emit_button_event(
            hass=hass,
            entry=entry,
            entry_data=entry_data,
            event_type=event_type,
            button=_BUTTON,
            sequence_counter=seq_val,
            rssi=_RSSI,
            mac_address=_MAC,
        )


def _fire_pending(
    pending: dict[int, tuple[float, Any, MagicMock]],
    delay: float,
    events: list[str],
    fake_call_later: Any,
) -> None:
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
    def test_press_then_release_emits_press_release_single(self) -> None:
        hass, entry, entry_data, pending, fake_call_later = _make_env()
        events: list[str] = []

        _emit(hass, entry, entry_data, "press", events, fake_call_later, seq=1)
        assert events == ["press", "single_press"]
        assert len(pending) == 2  # long_press + release_timeout timers scheduled

        _emit(hass, entry, entry_data, "release", events, fake_call_later, seq=2)
        assert events == ["press", "single_press", "release"]
        assert len(pending) == 0  # both timers cancelled

    def test_release_without_prior_press_emits_orphan_only(self) -> None:
        """First-ever release for a button with no prior press history → orphan, no single_press."""
        hass, entry, entry_data, pending, fake_call_later = _make_env()
        events: list[str] = []

        _emit(hass, entry, entry_data, "release", events, fake_call_later, seq=5)
        assert events == ["orphan_release"]
        assert len(pending) == 0


# ---------------------------------------------------------------------------
# Long press — normal (release arrives before timeout)
# ---------------------------------------------------------------------------

class TestLongPressNormal:
    def test_long_press_fires_and_schedules_timeout(self) -> None:
        hass, entry, entry_data, pending, fake_call_later = _make_env()
        events: list[str] = []

        _emit(hass, entry, entry_data, "press", events, fake_call_later, seq=1)
        assert len(pending) == 2  # long_press + release_timeout

        _fire_pending(pending, LONG_PRESS_SECONDS, events, fake_call_later)

        assert events == ["press", "single_press", "long_press"]
        assert len(pending) == 1  # only release_timeout remains
        delay, _, _ = next(iter(pending.values()))
        assert delay == RELEASE_TIMEOUT_SECONDS

    def test_release_after_long_press_emits_release_and_long_release_no_second_single(self) -> None:
        """Long press cycle must NOT emit a second single_press on release."""
        hass, entry, entry_data, pending, fake_call_later = _make_env()
        events: list[str] = []

        _emit(hass, entry, entry_data, "press", events, fake_call_later, seq=1)
        _fire_pending(pending, LONG_PRESS_SECONDS, events, fake_call_later)
        assert events == ["press", "single_press", "long_press"]
        assert len(pending) == 1  # release_timeout pending

        _emit(hass, entry, entry_data, "release", events, fake_call_later, seq=2)

        assert events == ["press", "single_press", "long_press", "release", "long_release"]
        assert events.count("single_press") == 1  # fired on press, not again on release
        assert len(pending) == 0  # release_timeout cancelled


# ---------------------------------------------------------------------------
# Release timeout — lost release
# ---------------------------------------------------------------------------

class TestReleaseTimeout:
    def test_timeout_fires_release_timeout_when_release_lost(self) -> None:
        hass, entry, entry_data, pending, fake_call_later = _make_env()
        events: list[str] = []

        _emit(hass, entry, entry_data, "press", events, fake_call_later, seq=1)
        _fire_pending(pending, LONG_PRESS_SECONDS, events, fake_call_later)
        assert events == ["press", "single_press", "long_press"]
        assert len(pending) == 1  # release_timeout pending

        _fire_pending(pending, RELEASE_TIMEOUT_SECONDS, events, fake_call_later)

        assert events == ["press", "single_press", "long_press", "release_timeout"]
        assert len(pending) == 0

    def test_new_press_cancels_pending_timeout(self) -> None:
        """Rule 3: a new press implicitly ends the previous open cycle."""
        hass, entry, entry_data, pending, fake_call_later = _make_env()
        events: list[str] = []

        _emit(hass, entry, entry_data, "press", events, fake_call_later, seq=1)
        _fire_pending(pending, LONG_PRESS_SECONDS, events, fake_call_later)
        assert len(pending) == 1  # release_timeout pending

        _emit(hass, entry, entry_data, "press", events, fake_call_later, seq=3)

        assert events[-2] == "press"
        assert events[-1] == "single_press"
        assert len(pending) == 2  # new long_press + release_timeout; old timeout was cancelled

    def test_timeout_is_noop_if_release_already_processed(self) -> None:
        """If timeout fires after release was already received, it must do nothing."""
        hass, entry, entry_data, pending, fake_call_later = _make_env()
        events: list[str] = []

        _emit(hass, entry, entry_data, "press", events, fake_call_later, seq=1)
        _fire_pending(pending, LONG_PRESS_SECONDS, events, fake_call_later)

        _emit(hass, entry, entry_data, "release", events, fake_call_later, seq=2)
        assert events == ["press", "single_press", "long_press", "release", "long_release"]

        state = entry_data["buttons"]["A0"]
        assert state["pressed_at"] is None
        assert not state["long_fired"]


# ---------------------------------------------------------------------------
# single_press dedup
# ---------------------------------------------------------------------------

class TestSinglePress:
    def test_single_press_fires_on_press_immediately(self) -> None:
        """single_press fires on press, before press duration is known."""
        hass, entry, entry_data, _pending, fake_call_later = _make_env()
        events: list[str] = []

        _emit(hass, entry, entry_data, "press", events, fake_call_later, seq=1)
        assert events.count("single_press") == 1
        assert events == ["press", "single_press"]

        _emit(hass, entry, entry_data, "release", events, fake_call_later, seq=2)
        assert events.count("single_press") == 1  # no second single_press on release
        assert events == ["press", "single_press", "release"]

    def test_single_press_fires_once_per_press_not_again_on_long_release(self) -> None:
        """single_press fires on press; must not fire a second time on long press release."""
        hass, entry, entry_data, pending, fake_call_later = _make_env()
        events: list[str] = []

        _emit(hass, entry, entry_data, "press", events, fake_call_later, seq=1)
        _fire_pending(pending, LONG_PRESS_SECONDS, events, fake_call_later)
        _emit(hass, entry, entry_data, "release", events, fake_call_later, seq=2)

        assert events.count("single_press") == 1  # fired on press, never again


# ---------------------------------------------------------------------------
# orphan_release coherence
# ---------------------------------------------------------------------------

class TestOrphanRelease:
    def test_orphan_coherent_fires_single_press(self) -> None:
        """Gap == 2 between last received seq and orphan release → coherent → single_press."""
        hass, entry, entry_data, _pending, fake_call_later = _make_env()
        events: list[str] = []

        # Complete a normal cycle to set last_received_seq = 2
        _emit(hass, entry, entry_data, "press", events, fake_call_later, seq=1)
        _emit(hass, entry, entry_data, "release", events, fake_call_later, seq=2)
        events.clear()

        # Press at seq=3 is lost; orphan release at seq=4 (gap = 4 - 2 = 2)
        _emit(hass, entry, entry_data, "release", events, fake_call_later, seq=4)
        assert events == ["orphan_release", "single_press"]

    def test_orphan_no_history_does_not_fire_single_press(self) -> None:
        """First event ever for this button is a release → old_seq is None → no single_press."""
        hass, entry, entry_data, _pending, fake_call_later = _make_env()
        events: list[str] = []

        _emit(hass, entry, entry_data, "release", events, fake_call_later, seq=5)
        assert events == ["orphan_release"]

    def test_orphan_nonconsecutive_does_not_fire_single_press(self) -> None:
        """Gap != 2 → stale orphan release → single_press not emitted."""
        hass, entry, entry_data, _pending, fake_call_later = _make_env()
        events: list[str] = []

        _emit(hass, entry, entry_data, "press", events, fake_call_later, seq=1)
        _emit(hass, entry, entry_data, "release", events, fake_call_later, seq=2)
        events.clear()

        # Gap = 7 - 2 = 5 ≠ 2 → stale
        _emit(hass, entry, entry_data, "release", events, fake_call_later, seq=7)
        assert events == ["orphan_release"]
