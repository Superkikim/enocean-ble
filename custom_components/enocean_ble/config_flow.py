"""Config flow for EnOcean BLE integration."""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from typing import Any

from homeassistant import config_entries
from homeassistant.components.bluetooth import (
    BluetoothServiceInfoBleak,
    async_discovered_service_info,
)
from homeassistant.data_entry_flow import FlowResult

from .const import (
    CONF_MAC_ADDRESS,
    CONF_SECURITY_KEY,
    DOMAIN,
    ENOCEAN_MAC_PREFIX,
    ENOCEAN_MANUFACTURER_ID,
    STATUS_BIT_A0,
    STATUS_BIT_A1,
    STATUS_BIT_B0,
    STATUS_BIT_B1,
    STATUS_BIT_ENERGY_BOW,
)
from .parser import parse_commissioning_telegram

_LOGGER = logging.getLogger(__name__)
FLOW_TAG = "[ENOCEAN_FLOW]"
CANCEL_TRACE_TAG = "FLOW_CANCEL_TRACE"
FLOW_TRACE_TAG = "FLOW_TRACE_V3"
UI_FLOW_PROGRESS_EVENT = "data_entry_flow_progressed"


class CommissioningNotActiveError(Exception):
    """Raised when commissioning mode is not active at the expected step."""


class EnOceanBleConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):  # type: ignore[misc,call-arg]
    """Handle a config flow for EnOcean BLE."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize config flow state."""
        self._pending_mac: str | None = None
        self._pending_title: str | None = None
        self._pending_security_key: str | None = None
        self._last_adv_time: float = 0.0
        self._stage_started_at: float = 0.0
        self._seen_payloads: set[tuple[float, int, str]] = set()
        self._next_match_not_before: float = 0.0
        self._commissioning_button_mask: int | None = None
        self._last_filter_signature: tuple[str, str, str] | None = None

        self._stage_task: asyncio.Task[None] | None = None
        self._stage_error: str | None = None
        self._last_progress_next_step: str | None = None
        self._last_progress_transition_at: float = 0.0
        self._commissioning_ready_for_exit: bool = False
        self._stage_started_monotonic: float = 0.0
        self._entry_created: bool = False
        self._terminal_cause_logged: bool = False
        self._flow_created_logged: bool = False
        self._active_stage_id: str | None = None
        self._stage_stats: dict[str, dict[str, Any]] = {}
        self._unsubscribe_ui_flow_progress: Any | None = None
        self._ui_progress_seen: bool = False
        self._ui_abort_explicit_seen: bool = False
        self._last_ui_progress_monotonic: float | None = None

    def async_remove(self) -> None:
        """Cleanup when flow is aborted/cancelled/finished by HA."""
        self._ensure_ui_progress_listener()
        current_step = None
        cur_step = getattr(self, "cur_step", None)
        if isinstance(cur_step, dict):
            current_step = cur_step.get("step_id")
        self._trace_event(
            "FLOW_REMOVED",
            step=current_step,
            note="Flow removed by Home Assistant flow manager.",
            has_entry=self._entry_created,
            next_step=self._last_progress_next_step,
            task_active=self._stage_task is not None and not self._stage_task.done(),
            ready_for_exit=self._commissioning_ready_for_exit,
        )
        _LOGGER.debug(
            "%s %s event=FLOW_REMOVED address=%s step=%s next=%s task_active=%s has_key=%s ready_for_exit=%s",
            FLOW_TAG,
            CANCEL_TRACE_TAG,
            self._pending_mac,
            current_step,
            self._last_progress_next_step,
            self._stage_task is not None and not self._stage_task.done(),
            self._pending_security_key is not None,
            self._commissioning_ready_for_exit,
        )
        self._log_terminal_cause_on_remove()
        self._remove_ui_progress_listener()
        self._cancel_stage_task(reason="flow_removed")

    async def async_step_bluetooth(self, discovery_info: BluetoothServiceInfoBleak) -> FlowResult:
        """Handle Bluetooth discovery and wait for explicit user confirmation."""
        self._ensure_ui_progress_listener()
        discovered_mac = discovery_info.address.upper()
        manufacturer_data = discovery_info.manufacturer_data.get(ENOCEAN_MANUFACTURER_ID)
        payload_hex = manufacturer_data.hex() if manufacturer_data else ""
        payload_len = len(manufacturer_data) if manufacturer_data else 0

        _LOGGER.debug(
            "%s DISCOVERY address=%s name=%s source=%s rssi=%s payload_len=%s payload_hex=%s",
            FLOW_TAG,
            discovered_mac,
            discovery_info.name,
            discovery_info.source,
            discovery_info.rssi,
            payload_len,
            payload_hex,
        )

        if not discovered_mac.startswith(ENOCEAN_MAC_PREFIX):
            return self.async_abort(reason="not_enocean_prefix")

        await self.async_set_unique_id(discovered_mac)
        self._abort_if_unique_id_configured()

        self._reset_progress_state(discovered_mac)
        self._pending_mac = discovered_mac
        self._pending_title = discovery_info.name or f"EnOcean BLE {discovered_mac[-8:]}"
        self.context["title_placeholders"] = {"name": self._pending_title}
        if not self._flow_created_logged:
            self._flow_created_logged = True
            self._trace_event(
                "FLOW_CREATED",
                step="bluetooth",
                note="Flow created from Bluetooth discovery.",
                discovered_name=discovery_info.name,
                source=discovery_info.source,
                rssi=discovery_info.rssi,
            )

        # If device is already in auto-commissioning mode at discovery time,
        # keep that result, but still wait for explicit user confirmation (Add click).
        if manufacturer_data is not None and len(manufacturer_data) == 26:
            _LOGGER.debug(
                "%s DISCOVERY_COMMISSIONING address=%s payload_len=26 payload_hex=%s",
                FLOW_TAG,
                discovered_mac,
                manufacturer_data.hex(),
            )
            try:
                self._apply_commissioning_payload(manufacturer_data)
            except ValueError:
                _LOGGER.debug(
                    "%s DISCOVERY_COMMISSIONING_INVALID address=%s payload_hex=%s",
                    FLOW_TAG,
                    discovered_mac,
                    manufacturer_data.hex(),
                )
            else:
                self._commissioning_ready_for_exit = True

        return await self.async_step_bluetooth_confirm()

    async def async_step_bluetooth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Wait for explicit user Add click before starting commissioning stages."""
        if self._pending_mac is None:
            return self.async_abort(reason="no_bluetooth_discovery")

        if user_input is None:
            self._trace_event(
                "FLOW_CONFIRM_SHOWN",
                step="bluetooth_confirm",
                note="Waiting for explicit user Add confirmation.",
            )
            return self.async_show_form(
                step_id="bluetooth_confirm",
                description_placeholders={"name": self._pending_title or self._pending_mac},
            )

        _LOGGER.debug(
            "%s USER_ADD_CONFIRMED address=%s",
            FLOW_TAG,
            self._pending_mac,
        )
        self._trace_event(
            "FLOW_USER_ADD_CONFIRMED",
            step="bluetooth_confirm",
            note="User confirmed Add in the UI.",
        )
        # Treat every explicit "Add" confirmation as a fresh run.
        # This avoids resuming a previously abandoned mid-flow stage.
        if self._pending_security_key is not None and self._commissioning_ready_for_exit:
            self._arm_progress_state_from_now(self._pending_mac)
            return await self.async_step_commissioning_exit_mode()
        self._reset_progress_state(self._pending_mac)
        _LOGGER.debug(
            "%s USER_ADD_FORCE_RESTART address=%s",
            FLOW_TAG,
            self._pending_mac,
        )
        return await self.async_step_commissioning_hold_1()

    async def async_step_commissioning_hold_1(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Step 1: hold button 1 for 7 seconds."""
        return await self._async_run_stage(
            step_id="commissioning_hold_1",
            progress_action="hold_button_1_7s",
            coro=self._async_stage_hold_one,
            next_step_id="commissioning_click_short",
        )

    async def async_step_commissioning_click_short(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Step 2: click button 1 briefly."""
        return await self._async_run_stage(
            step_id="commissioning_click_short",
            progress_action="click_button_1_briefly",
            coro=self._async_stage_click_short,
            next_step_id="commissioning_hold_2",
        )

    async def async_step_commissioning_hold_2(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Step 3: hold again and wait for commissioning telegram."""
        return await self._async_run_stage(
            step_id="commissioning_hold_2",
            progress_action="hold_button_1_again_7s",
            coro=self._async_stage_hold_two,
            next_step_id="commissioning_release_2",
        )

    async def async_step_commissioning_release_2(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Step 4: click again briefly and confirm commissioning telegram."""
        return await self._async_run_stage(
            step_id="commissioning_release_2",
            progress_action="click_button_1_again_briefly",
            coro=self._async_stage_release_two_and_commission,
            next_step_id="commissioning_exit_mode",
        )

    async def async_step_commissioning_exit_mode(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Step 5: ask user to exit auto-commissioning mode."""
        return await self._async_run_stage(
            step_id="commissioning_exit_mode",
            progress_action="click_another_button_to_exit_commissioning",
            coro=self._async_stage_exit_commissioning_mode,
            next_step_id="commissioning_active",
        )

    async def async_step_commissioning_active(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Final step: auto-commissioning active, create entry."""
        if self._pending_mac is None or self._pending_security_key is None:
            return self.async_show_form(
                step_id="commissioning_hold_1",
                errors={"base": "commissioning_not_detected"},
                description_placeholders={"name": self._pending_title or "EnOcean BLE"},
            )

        _LOGGER.debug(
            "flow_commissioning_create_entry address=%s title=%s",
            self._pending_mac,
            self._pending_title,
        )
        self._entry_created = True
        self._trace_event(
            "FLOW_CREATE_ENTRY",
            step="commissioning_active",
            note="Commissioning succeeded and config entry is being created.",
            title=self._pending_title or "EnOcean BLE Switch",
        )
        return self.async_create_entry(
            title=self._pending_title or "EnOcean BLE Switch",
            data={
                CONF_MAC_ADDRESS: self._pending_mac,
                CONF_SECURITY_KEY: self._pending_security_key,
            },
        )

    async def _async_run_stage(
        self,
        *,
        step_id: str,
        progress_action: str,
        coro: Any,
        next_step_id: str,
    ) -> FlowResult:
        """Run one monitored stage with automatic progression."""
        if self._pending_mac is None:
            return self.async_abort(reason="no_bluetooth_discovery")

        # If the UI was closed and resumed later, HA can re-enter a mid-flow step.
        # Force a clean restart so "Add" always restarts from step 1.
        now = self.hass.loop.time()
        if (
            step_id != "commissioning_hold_1"
            and self._stage_task is None
            and (
                self._last_progress_next_step != step_id
                or (now - self._last_progress_transition_at) > 2.0
            )
        ):
            _LOGGER.debug(
                "%s STALE_STEP_RESTART from_step=%s expected_next=%s age=%.3fs",
                FLOW_TAG,
                step_id,
                self._last_progress_next_step,
                now - self._last_progress_transition_at,
            )
            self._reset_progress_state(self._pending_mac)
            _LOGGER.debug(
                "%s %s event=STALE_FLOW_TO_CONFIRM address=%s from_step=%s",
                FLOW_TAG,
                CANCEL_TRACE_TAG,
                self._pending_mac,
                step_id,
            )
            return await self.async_step_bluetooth_confirm()

        if self._stage_task is None:
            self._stage_started_at = max(self._last_adv_time, self._max_adv_time_for_mac(self._pending_mac))
            self._stage_started_monotonic = self._monotonic_now()
            self._active_stage_id = step_id
            self._ensure_stage_stats(step_id)
            self._stage_task = self.hass.async_create_task(coro())
            _LOGGER.debug(
                "%s STAGE_START step=%s address=%s stage_started_at=%s",
                FLOW_TAG,
                step_id,
                self._pending_mac,
                self._stage_started_at,
            )
            self._trace_event(
                "FLOW_STAGE_ENTER",
                step=step_id,
                note="Stage task started.",
                progress_action=progress_action,
                next_step=next_step_id,
            )

        if not self._stage_task.done():
            return self.async_show_progress(
                step_id=step_id,
                progress_action=progress_action,
                progress_task=self._stage_task,
                description_placeholders={"name": self._pending_title or self._pending_mac},
            )

        try:
            self._stage_task.result()
        except TimeoutError:
            self._stage_error = "commissioning_not_detected"
            self._trace_event(
                "FLOW_STAGE_TIMEOUT",
                step=step_id,
                note="Stage timed out waiting for expected telemetry.",
                error=self._stage_error,
            )
        except CommissioningNotActiveError:
            self._stage_error = "commissioning_not_active"
            self._trace_event(
                "FLOW_STAGE_ERROR",
                step=step_id,
                note="Stage failed because commissioning mode was not active.",
                error=self._stage_error,
            )
        except ValueError:
            self._stage_error = "invalid_commissioning"
            self._trace_event(
                "FLOW_STAGE_ERROR",
                step=step_id,
                note="Stage failed because commissioning payload was invalid.",
                error=self._stage_error,
            )

        self._stage_task = None
        if self._stage_error is not None:
            error = self._stage_error
            self._stage_error = None
            self._log_stage_summary(step_id=step_id)
            self._active_stage_id = None
            _LOGGER.debug(
                "%s STAGE_ERROR step=%s error=%s address=%s",
                FLOW_TAG,
                step_id,
                error,
                self._pending_mac,
            )
            return self.async_show_form(
                step_id=step_id,
                errors={"base": error},
                description_placeholders={"name": self._pending_title or self._pending_mac},
            )

        self._trace_event(
            "FLOW_STAGE_EXIT",
            step=step_id,
            note="Stage completed successfully.",
            next_step=next_step_id,
        )
        self._log_stage_summary(step_id=step_id)
        if step_id == "commissioning_hold_2" and self._commissioning_ready_for_exit:
            self._commissioning_ready_for_exit = False
            self._last_progress_next_step = "commissioning_exit_mode"
            self._last_progress_transition_at = self.hass.loop.time()
            self._active_stage_id = None
            return self.async_show_progress_done(next_step_id="commissioning_exit_mode")

        self._last_progress_next_step = next_step_id
        self._last_progress_transition_at = self.hass.loop.time()
        self._active_stage_id = None
        return self.async_show_progress_done(next_step_id=next_step_id)

    async def _async_stage_hold_one(self) -> None:
        """Wait for first len=9 telegram then hold duration."""
        _LOGGER.debug("%s STEP1 start: waiting A0 press (energy bow) then enforcing hold 7s", FLOW_TAG)
        await self._async_wait_for_payload_len(
            9,
            timeout=25.0,
            stage_label="STEP1",
            require_press=True,
            expected_button_mask=STATUS_BIT_A0,
        )
        await asyncio.sleep(7.0)
        # Ignore immediate release telegram right after the long hold.
        self._next_match_not_before = self.hass.loop.time() + 1.2
        _LOGGER.debug("%s STEP1 complete", FLOW_TAG)

    async def _async_stage_click_short(self) -> None:
        """Wait for a short click start telegram (A0 press with energy bow)."""
        _LOGGER.debug("%s STEP2 start: waiting A0 press (energy bow) for short click", FLOW_TAG)
        await self._async_wait_for_payload_len(
            9,
            timeout=20.0,
            stage_label="STEP2",
            require_press=True,
            expected_button_mask=STATUS_BIT_A0,
        )
        # Small guard window before entering step3.
        self._next_match_not_before = self.hass.loop.time() + 0.6
        _LOGGER.debug("%s STEP2 complete", FLOW_TAG)

    async def _async_stage_hold_two(self) -> None:
        """Wait for second hold start (A0 press) or direct commissioning telegram."""
        _LOGGER.debug("%s STEP3 start: waiting A0 press (energy bow) OR LEN=26 commissioning", FLOW_TAG)
        first_kind, payload = await self._async_wait_for_len9_or_commissioning(
            timeout=25.0,
            stage_label="STEP3",
            len9_require_press=True,
            len9_expected_button_mask=STATUS_BIT_A0,
        )
        if first_kind == "commissioning":
            _LOGGER.debug("%s STEP3 commissioning detected directly", FLOW_TAG)
            self._apply_commissioning_payload(payload)
            self._commissioning_ready_for_exit = True
            return

        await asyncio.sleep(7.0)
        self._next_match_not_before = self.hass.loop.time()
        _LOGGER.debug("%s STEP3 complete: hold duration reached", FLOW_TAG)

    async def _async_stage_release_two_and_commission(self) -> None:
        """Wait for brief click confirmation and require commissioning telegram."""
        _LOGGER.debug("%s STEP4 start: waiting LEN=9 or LEN=26 (confirmation click)", FLOW_TAG)
        first_kind, payload = await self._async_wait_for_any_or_commissioning(
            timeout=35.0,
            stage_label="STEP4",
        )
        if first_kind == "commissioning":
            _LOGGER.debug("%s STEP4 commissioning detected first", FLOW_TAG)
            self._apply_commissioning_payload(payload)
            _LOGGER.debug("%s STEP4 complete: commissioning payload accepted", FLOW_TAG)
            return

        _LOGGER.debug("%s STEP4 len=9 detected first; waiting LEN=26 confirmation", FLOW_TAG)
        try:
            payload = await self._async_wait_for_payload_len(26, timeout=20.0, stage_label="STEP4")
        except TimeoutError as err:
            _LOGGER.debug(
                "%s STEP4 FAIL first_kind=%s reason=commissioning_not_active",
                FLOW_TAG,
                first_kind,
            )
            raise CommissioningNotActiveError from err

        self._apply_commissioning_payload(payload)
        self._commissioning_ready_for_exit = True
        _LOGGER.debug("%s STEP4 complete: commissioning payload accepted", FLOW_TAG)

    async def _async_wait_for_any_or_commissioning(
        self,
        *,
        timeout: float,
        stage_label: str,
    ) -> tuple[str, bytes]:
        """Wait for first relevant event: any LEN=9 telegram or LEN=26 commissioning telegram."""
        if self._pending_mac is None:
            raise TimeoutError("No pending MAC")

        deadline = self.hass.loop.time() + timeout
        min_time = max(self._last_adv_time, self._stage_started_at, self._next_match_not_before)
        while self.hass.loop.time() < deadline:
            candidates: list[tuple[float, str, bytes]] = []
            for info in async_discovered_service_info(self.hass):
                if info.address.upper() != self._pending_mac:
                    continue
                info_time = float(getattr(info, "time", 0.0) or 0.0)
                if info_time <= min_time:
                    continue
                payload = info.manufacturer_data.get(ENOCEAN_MANUFACTURER_ID)
                if payload is None:
                    continue
                if len(payload) == 9:
                    candidates.append((info_time, "len9", payload))
                elif len(payload) == 26:
                    candidates.append((info_time, "commissioning", payload))

            if not candidates:
                await asyncio.sleep(0.3)
                continue

            info_time, kind, payload = min(candidates, key=lambda item: item[0])
            signature = (info_time, len(payload), payload.hex())
            if signature in self._seen_payloads:
                self._record_payload_candidate(
                    stage_label=stage_label,
                    payload=payload,
                    info_time=info_time,
                    decision="duplicate",
                    reject_reason="already_seen",
                )
                await asyncio.sleep(0.2)
                continue

            self._seen_payloads.add(signature)
            self._last_adv_time = info_time
            self._record_payload_candidate(
                stage_label=stage_label,
                payload=payload,
                info_time=info_time,
                decision="accepted",
            )
            if kind == "len9":
                status = payload[4]
                _LOGGER.debug(
                    "%s %s FIRST kind=%s address=%s payload_len=%s timestamp=%s payload_hex=%s status=0x%02x inferred=%s button_mask=0x%02x",
                    FLOW_TAG,
                    stage_label,
                    kind,
                    self._pending_mac,
                    len(payload),
                    info_time,
                    payload.hex(),
                    status,
                    "press" if _is_press_status(status) else "release",
                    _button_mask(payload),
                )
            else:
                _LOGGER.debug(
                    "%s %s FIRST kind=%s address=%s payload_len=%s timestamp=%s payload_hex=%s",
                    FLOW_TAG,
                    stage_label,
                    kind,
                    self._pending_mac,
                    len(payload),
                    info_time,
                    payload.hex(),
                )
            return kind, payload

        recent = self._recent_payload_snapshot(self._pending_mac, max_items=8)
        _LOGGER.debug(
            "%s %s TIMEOUT waiting=any_len9_or_commissioning timeout=%ss last_adv_time=%s recent_payloads=%s",
            FLOW_TAG,
            stage_label,
            timeout,
            self._last_adv_time,
            recent,
        )
        raise TimeoutError("Any len=9 or commissioning telegram not detected")

    async def _async_wait_for_len9_or_commissioning(
        self,
        *,
        timeout: float,
        stage_label: str,
        len9_require_press: bool = False,
        len9_require_release: bool = False,
        len9_expected_button_mask: int | None = None,
        len9_forbidden_button_mask: int | None = None,
    ) -> tuple[str, bytes]:
        """Wait for first relevant event: LEN=9 telegram or commissioning (LEN=26)."""
        if self._pending_mac is None:
            raise TimeoutError("No pending MAC")

        deadline = self.hass.loop.time() + timeout
        min_time = max(self._last_adv_time, self._stage_started_at, self._next_match_not_before)
        while self.hass.loop.time() < deadline:
            len9_payload, len9_time = self._find_latest_payload(
                self._pending_mac,
                9,
                min_time,
                stage_label=stage_label,
                require_press=len9_require_press,
                require_release=len9_require_release,
                expected_button_mask=len9_expected_button_mask,
                forbidden_button_mask=len9_forbidden_button_mask,
            )
            comm_payload, comm_time = self._find_latest_payload(
                self._pending_mac,
                26,
                min_time,
                stage_label=stage_label,
                require_press=False,
                require_release=False,
                expected_button_mask=None,
                forbidden_button_mask=None,
            )

            candidates: list[tuple[float, str, bytes]] = []
            if len9_payload is not None and len9_time is not None:
                candidates.append((len9_time, "len9", len9_payload))
            if comm_payload is not None and comm_time is not None:
                candidates.append((comm_time, "commissioning", comm_payload))

            if not candidates:
                await asyncio.sleep(0.3)
                continue

            info_time, kind, payload = min(candidates, key=lambda item: item[0])
            signature = (info_time, len(payload), payload.hex())
            if signature in self._seen_payloads:
                self._record_payload_candidate(
                    stage_label=stage_label,
                    payload=payload,
                    info_time=info_time,
                    decision="duplicate",
                    reject_reason="already_seen",
                )
                await asyncio.sleep(0.2)
                continue

            self._seen_payloads.add(signature)
            self._last_adv_time = info_time
            self._record_payload_candidate(
                stage_label=stage_label,
                payload=payload,
                info_time=info_time,
                decision="accepted",
            )
            _LOGGER.debug(
                "%s %s FIRST kind=%s address=%s payload_len=%s timestamp=%s payload_hex=%s",
                FLOW_TAG,
                stage_label,
                kind,
                self._pending_mac,
                len(payload),
                info_time,
                payload.hex(),
            )
            return kind, payload

        recent = self._recent_payload_snapshot(self._pending_mac, max_items=8)
        _LOGGER.debug(
            "%s %s TIMEOUT waiting=len9_or_commissioning timeout=%ss last_adv_time=%s recent_payloads=%s",
            FLOW_TAG,
            stage_label,
            timeout,
            self._last_adv_time,
            recent,
        )
        raise TimeoutError("LEN=9 or commissioning telegram not detected")

    async def _async_stage_exit_commissioning_mode(self) -> None:
        """Require a real press on button 2 (A1) to exit auto-commissioning mode."""
        _LOGGER.debug("%s STEP5 start: waiting A1 press (energy bow) to confirm exit action", FLOW_TAG)
        await self._async_wait_for_payload_len(
            9,
            timeout=25.0,
            stage_label="STEP5",
            require_press=True,
            expected_button_mask=STATUS_BIT_A1,
        )
        _LOGGER.debug("%s STEP5 complete: A1 press detected, exit action confirmed", FLOW_TAG)

    async def _async_wait_for_len9_count(self, *, count: int, timeout: float, stage_label: str) -> None:
        """Wait for a number of distinct LEN=9 telegrams."""
        seen = 0
        while seen < count:
            await self._async_wait_for_payload_len(
                9,
                timeout=timeout,
                stage_label=f"{stage_label}.{seen + 1}/{count}",
            )
            seen += 1
        _LOGGER.debug("%s %s COUNT_MATCH count=%s", FLOW_TAG, stage_label, count)

    async def _async_wait_for_payload_len(
        self,
        target_len: int,
        *,
        timeout: float,
        stage_label: str,
        require_press: bool = False,
        require_release: bool = False,
        expected_button_mask: int | None = None,
        forbidden_button_mask: int | None = None,
    ) -> bytes:
        """Wait for next advertisement payload with given length."""
        if self._pending_mac is None:
            raise TimeoutError("No pending MAC")

        deadline = self.hass.loop.time() + timeout
        min_time = max(self._last_adv_time, self._stage_started_at, self._next_match_not_before)
        while self.hass.loop.time() < deadline:
            payload, info_time = self._find_latest_payload(
                self._pending_mac,
                target_len,
                min_time,
                stage_label=stage_label,
                require_press=require_press,
                require_release=require_release,
                expected_button_mask=expected_button_mask,
                forbidden_button_mask=forbidden_button_mask,
            )
            if payload is not None and info_time is not None:
                signature = (info_time, target_len, payload.hex())
                if signature in self._seen_payloads:
                    self._record_payload_candidate(
                        stage_label=stage_label,
                        payload=payload,
                        info_time=info_time,
                        decision="duplicate",
                        reject_reason="already_seen",
                    )
                    await asyncio.sleep(0.2)
                    continue
                self._seen_payloads.add(signature)
                self._last_adv_time = info_time
                self._record_payload_candidate(
                    stage_label=stage_label,
                    payload=payload,
                    info_time=info_time,
                    decision="accepted",
                )
                _LOGGER.debug(
                    "%s %s MATCH address=%s payload_len=%s timestamp=%s payload_hex=%s",
                    FLOW_TAG,
                    stage_label,
                    self._pending_mac,
                    target_len,
                    info_time,
                    payload.hex(),
                )
                return payload
            await asyncio.sleep(0.3)

        recent = self._recent_payload_snapshot(self._pending_mac, max_items=8)
        _LOGGER.debug(
            "%s %s TIMEOUT waiting_len=%s timeout=%ss last_adv_time=%s recent_payloads=%s",
            FLOW_TAG,
            stage_label,
            target_len,
            timeout,
            self._last_adv_time,
            recent,
        )
        raise TimeoutError(f"Payload len={target_len} not detected")

    def _find_latest_payload(
        self,
        mac_address: str,
        target_len: int,
        min_time: float,
        *,
        stage_label: str,
        require_press: bool,
        require_release: bool,
        expected_button_mask: int | None,
        forbidden_button_mask: int | None,
    ) -> tuple[bytes | None, float | None]:
        """Find latest payload for MAC with exact length and newer than min_time."""
        latest_payload: bytes | None = None
        latest_time: float | None = None

        for info in async_discovered_service_info(self.hass):
            if info.address.upper() != mac_address:
                continue
            info_time = float(getattr(info, "time", 0.0) or 0.0)
            if info_time <= min_time:
                continue
            payload = info.manufacturer_data.get(ENOCEAN_MANUFACTURER_ID)
            if payload is None or len(payload) != target_len:
                continue
            if target_len == 9:
                status = payload[4]
                if require_press and not _is_press_status(status):
                    self._record_payload_candidate(
                        stage_label=stage_label,
                        payload=payload,
                        info_time=info_time,
                        decision="rejected",
                        reject_reason="release_ignored",
                    )
                    self._log_filter_once(
                        stage_label=stage_label,
                        reason="release_ignored",
                        payload_hex=payload.hex(),
                    )
                    continue
                if require_release and _is_press_status(status):
                    self._record_payload_candidate(
                        stage_label=stage_label,
                        payload=payload,
                        info_time=info_time,
                        decision="rejected",
                        reject_reason="press_ignored",
                    )
                    self._log_filter_once(
                        stage_label=stage_label,
                        reason="press_ignored",
                        payload_hex=payload.hex(),
                    )
                    continue
                if expected_button_mask is not None and _button_mask(payload) != expected_button_mask:
                    self._record_payload_candidate(
                        stage_label=stage_label,
                        payload=payload,
                        info_time=info_time,
                        decision="rejected",
                        reject_reason="button_mismatch",
                    )
                    self._log_filter_once(
                        stage_label=stage_label,
                        reason="button_mismatch",
                        payload_hex=payload.hex(),
                    )
                    continue
                if forbidden_button_mask is not None and _button_mask(payload) == forbidden_button_mask:
                    self._record_payload_candidate(
                        stage_label=stage_label,
                        payload=payload,
                        info_time=info_time,
                        decision="rejected",
                        reject_reason="same_button_ignored",
                    )
                    self._log_filter_once(
                        stage_label=stage_label,
                        reason="same_button_ignored",
                        payload_hex=payload.hex(),
                    )
                    continue
            if latest_time is None or info_time > latest_time:
                self._record_payload_candidate(
                    stage_label=stage_label,
                    payload=payload,
                    info_time=info_time,
                    decision="candidate_selected",
                )
                latest_time = info_time
                latest_payload = payload
            else:
                self._record_payload_candidate(
                    stage_label=stage_label,
                    payload=payload,
                    info_time=info_time,
                    decision="rejected",
                    reject_reason="older_than_selected",
                )

        return latest_payload, latest_time

    def _log_filter_once(self, *, stage_label: str, reason: str, payload_hex: str) -> None:
        """Avoid spamming identical filter logs for repeated cached advertisements."""
        signature = (stage_label, reason, payload_hex)
        if signature == self._last_filter_signature:
            return
        self._last_filter_signature = signature
        _LOGGER.debug(
            "%s STAGE_FILTER stage=%s mac=%s reason=%s payload_hex=%s",
            FLOW_TAG,
            stage_label,
            self._pending_mac,
            reason,
            payload_hex,
        )

    def _apply_commissioning_payload(self, payload: bytes) -> None:
        """Parse commissioning payload and store security key after MAC validation."""
        commissioning = parse_commissioning_telegram(payload)

        if self._pending_mac is None:
            raise ValueError("No pending MAC")

        payload_mac = _format_mac(commissioning.static_source_address_hex)
        payload_mac_reversed = _format_mac(_reverse_mac_hex(commissioning.static_source_address_hex))
        if self._pending_mac not in {payload_mac, payload_mac_reversed}:
            _LOGGER.debug(
                "flow_stage_mismatch address=%s payload_mac=%s payload_mac_reversed=%s",
                self._pending_mac,
                payload_mac,
                payload_mac_reversed,
            )
            raise ValueError("commissioning_static_source_mismatch")

        self._pending_security_key = commissioning.security_key_hex
        _LOGGER.debug(
            "%s COMMISSIONING_OK address=%s sequence_counter=%s",
            FLOW_TAG,
            self._pending_mac,
            commissioning.sequence_counter,
        )

    def _max_adv_time_for_mac(self, mac_address: str) -> float:
        """Return latest known advertisement timestamp for MAC."""
        max_time = 0.0
        for info in async_discovered_service_info(self.hass):
            if info.address.upper() != mac_address:
                continue
            max_time = max(max_time, float(getattr(info, "time", 0.0) or 0.0))
        return max_time

    def _reset_progress_state(self, mac_address: str) -> None:
        """Reset staged monitoring state for a fresh flow run."""
        self._cancel_stage_task(reason="reset_progress_state")
        self._pending_security_key = None
        self._stage_error = None
        self._seen_payloads.clear()
        self._next_match_not_before = 0.0
        self._commissioning_button_mask = None
        self._last_filter_signature = None
        self._last_progress_next_step = None
        self._last_progress_transition_at = 0.0
        self._commissioning_ready_for_exit = False
        self._active_stage_id = None
        self._stage_stats.clear()
        self._stage_started_monotonic = self._monotonic_now()
        self._last_adv_time = self._max_adv_time_for_mac(mac_address)
        self._stage_started_at = self._last_adv_time
        _LOGGER.debug(
            "%s RESET address=%s baseline_adv_time=%s",
            FLOW_TAG,
            mac_address,
            self._last_adv_time,
        )

    def _arm_progress_state_from_now(self, mac_address: str) -> None:
        """Re-arm stage matching from user confirmation time without wiping discovered key."""
        self._cancel_stage_task(reason="arm_from_user_add")
        self._stage_error = None
        self._seen_payloads.clear()
        self._next_match_not_before = 0.0
        self._last_filter_signature = None
        self._last_progress_next_step = None
        self._last_progress_transition_at = 0.0
        self._active_stage_id = None
        self._stage_stats.clear()
        self._stage_started_monotonic = self._monotonic_now()
        self._last_adv_time = self._max_adv_time_for_mac(mac_address)
        self._stage_started_at = self._last_adv_time
        _LOGGER.debug(
            "%s ARM_FROM_USER_ADD address=%s baseline_adv_time=%s",
            FLOW_TAG,
            mac_address,
            self._last_adv_time,
        )

    def _cancel_stage_task(self, *, reason: str) -> None:
        """Cancel in-flight stage task so cancel/retry starts from a clean state."""
        if self._stage_task is None:
            return
        if not self._stage_task.done():
            self._stage_task.cancel()
            _LOGGER.debug(
                "%s %s event=STAGE_TASK_CANCELLED reason=%s address=%s",
                FLOW_TAG,
                CANCEL_TRACE_TAG,
                reason,
                self._pending_mac,
            )
        self._stage_task = None

    def _recent_payload_snapshot(self, mac_address: str, *, max_items: int) -> list[str]:
        """Return a compact snapshot of recent payloads for debug analysis."""
        items: list[tuple[float, str]] = []
        for info in async_discovered_service_info(self.hass):
            if info.address.upper() != mac_address:
                continue
            payload = info.manufacturer_data.get(ENOCEAN_MANUFACTURER_ID)
            if payload is None:
                continue
            info_time = float(getattr(info, "time", 0.0) or 0.0)
            items.append((info_time, f"{info_time:.3f}:len={len(payload)}:{payload.hex()}"))
        items.sort(key=lambda it: it[0], reverse=True)
        return [line for _, line in items[:max_items]]

    def _monotonic_now(self) -> float:
        """Return current monotonic timestamp."""
        if hasattr(self, "hass"):
            return float(self.hass.loop.time())
        return 0.0

    def _current_step_id(self) -> str:
        """Return current step ID when available."""
        cur_step = getattr(self, "cur_step", None)
        if isinstance(cur_step, dict):
            step_id = cur_step.get("step_id")
            if isinstance(step_id, str):
                return step_id
        return self._active_stage_id or "unknown"

    def _trace_event(self, event: str, *, step: str | None = None, note: str = "", **fields: Any) -> None:
        """Emit normalized FLOW_TRACE_V3 logs with correlation fields."""
        monotonic_ts = self._monotonic_now()
        delta_stage_ms: float | None = None
        if self._stage_started_monotonic > 0:
            delta_stage_ms = round((monotonic_ts - self._stage_started_monotonic) * 1000, 3)
        delta_last_seen_ms: float | None = None
        if self._last_adv_time > 0:
            delta_last_seen_ms = round((monotonic_ts - self._last_adv_time) * 1000, 3)

        payload_fields = {
            "flow_id": getattr(self, "flow_id", "unknown"),
            "mac": self._pending_mac,
            "step": step or self._current_step_id(),
            "monotonic_ts": round(monotonic_ts, 6),
            "delta_stage_ms": delta_stage_ms,
            "delta_last_seen_ms": delta_last_seen_ms,
            "note": note,
        }
        payload_fields.update(fields)
        field_str = " ".join(f"{key}={value}" for key, value in payload_fields.items())
        _LOGGER.debug("%s %s event=%s %s", FLOW_TAG, FLOW_TRACE_TAG, event, field_str)

    def _ensure_stage_stats(self, step_id: str) -> None:
        """Ensure stage counters exist."""
        if step_id in self._stage_stats:
            return
        self._stage_stats[step_id] = {
            "total_seen": 0,
            "accepted": 0,
            "duplicates": 0,
            "rejected_by_reason": defaultdict(int),
            "last_payload_ts": None,
        }

    def _record_payload_candidate(
        self,
        *,
        stage_label: str,
        payload: bytes,
        info_time: float,
        decision: str,
        reject_reason: str | None = None,
    ) -> None:
        """Record and log each payload candidate seen during stage evaluation."""
        step_id = self._active_stage_id or self._current_step_id()
        self._ensure_stage_stats(step_id)
        stats = self._stage_stats[step_id]
        stats["total_seen"] += 1
        stats["last_payload_ts"] = info_time
        if decision in {"accepted", "candidate_selected"}:
            stats["accepted"] += 1
        if decision == "duplicate":
            stats["duplicates"] += 1
        if reject_reason is not None:
            rejected = stats["rejected_by_reason"]
            rejected[reject_reason] += 1

        status = payload[4] if len(payload) >= 5 else None
        inferred_event = "unknown"
        button_mask = None
        if len(payload) == 9 and status is not None:
            inferred_event = "press" if _is_press_status(status) else "release"
            button_mask = f"0x{_button_mask(payload):02x}"
        elif len(payload) == 26:
            inferred_event = "commissioning"
        self._trace_event(
            "FLOW_PAYLOAD_CANDIDATE",
            step=step_id,
            note="Evaluating a payload candidate for the active stage.",
            stage_label=stage_label,
            payload_hex=payload.hex(),
            len=len(payload),
            status=f"0x{status:02x}" if status is not None else None,
            inferred_event=inferred_event,
            button_mask=button_mask,
            decision=decision,
            reject_reason=reject_reason,
            payload_ts=round(info_time, 6),
        )

    def _log_stage_summary(self, *, step_id: str) -> None:
        """Log summary counters for a completed stage."""
        self._ensure_stage_stats(step_id)
        stats = self._stage_stats[step_id]
        rejected: dict[str, int] = dict(stats["rejected_by_reason"])
        self._trace_event(
            "FLOW_STAGE_SUMMARY",
            step=step_id,
            note="Stage candidate evaluation summary.",
            total_seen=stats["total_seen"],
            accepted=stats["accepted"],
            rejected_by_reason=rejected,
            duplicates=stats["duplicates"],
            last_payload_ts=stats["last_payload_ts"],
        )

    def _ensure_ui_progress_listener(self) -> None:
        """Subscribe once to data_entry_flow_progressed for flow intent correlation."""
        if self._unsubscribe_ui_flow_progress is not None:
            return
        if not hasattr(self, "hass"):
            return

        def _on_progress(event: Any) -> None:
            data = getattr(event, "data", None)
            if isinstance(data, dict):
                self._handle_ui_flow_progress_event(data)

        self._unsubscribe_ui_flow_progress = self.hass.bus.async_listen(UI_FLOW_PROGRESS_EVENT, _on_progress)

    def _remove_ui_progress_listener(self) -> None:
        """Unsubscribe from flow progress events."""
        if self._unsubscribe_ui_flow_progress is None:
            return
        self._unsubscribe_ui_flow_progress()
        self._unsubscribe_ui_flow_progress = None

    def _handle_ui_flow_progress_event(self, data: dict[str, Any]) -> None:
        """Correlate frontend flow progress events with this flow."""
        flow_id = data.get("flow_id")
        if flow_id != getattr(self, "flow_id", None):
            return

        now = self._monotonic_now()
        self._ui_progress_seen = True
        self._last_ui_progress_monotonic = now
        result = data.get("result")
        result_type = result.get("type") if isinstance(result, dict) else data.get("type")
        reason = result.get("reason") if isinstance(result, dict) else data.get("reason")
        self._trace_event(
            "UI_FLOW_PROGRESS_OBSERVED",
            step=data.get("step_id"),
            note="Observed data_entry_flow_progressed event for this flow.",
            result_type=result_type,
            reason=reason,
        )

        if result_type == "abort":
            self._ui_abort_explicit_seen = True
            self._trace_event(
                "USER_INTENT_ABORT_EXPLICIT",
                step=data.get("step_id"),
                note="Explicit abort observed on flow progress channel.",
                confidence="high",
                reason=reason,
            )

    def _log_terminal_cause_on_remove(self) -> None:
        """Log terminal interpretation when flow is removed without entry creation."""
        if self._terminal_cause_logged:
            return
        self._terminal_cause_logged = True
        if self._entry_created:
            return

        now = self._monotonic_now()
        if self._ui_abort_explicit_seen:
            self._trace_event(
                "FLOW_TERMINATED_WITHOUT_ENTRY",
                note="Flow terminated without creating an entry after explicit abort.",
                cause="USER_INTENT_ABORT_EXPLICIT",
                confidence="high",
            )
            return

        if self._ui_progress_seen and self._last_ui_progress_monotonic is not None:
            silence_ms = round((now - self._last_ui_progress_monotonic) * 1000, 3)
            if silence_ms >= 1500:
                self._trace_event(
                    "USER_INTENT_UI_CLOSE_SUSPECTED",
                    note="UI progression disappeared before removal, close/navigation suspected.",
                    confidence="medium",
                    silence_ms=silence_ms,
                )
                self._trace_event(
                    "FLOW_TERMINATED_WITHOUT_ENTRY",
                    note="Flow removed with UI-close suspicion and no created entry.",
                    cause="USER_INTENT_UI_CLOSE_SUSPECTED",
                    confidence="medium",
                )
                return

        self._trace_event(
            "TERMINATION_CAUSE_UNKNOWN",
            note="Removed without entry and without reliable user-intent proof.",
            confidence="low",
        )
        self._trace_event(
            "FLOW_TERMINATED_WITHOUT_ENTRY",
            note="Flow removed without entry and cause could not be proven.",
            cause="TERMINATION_CAUSE_UNKNOWN",
            confidence="low",
        )


def _reverse_mac_hex(mac_hex: str) -> str:
    """Reverse byte order of a 12-hex MAC string."""
    octets = [mac_hex[i : i + 2] for i in range(0, 12, 2)]
    return "".join(reversed(octets))


def _format_mac(mac_hex: str) -> str:
    """Format a 12-hex MAC string as AA:BB:CC:DD:EE:FF."""
    return ":".join(mac_hex[i : i + 2] for i in range(0, 12, 2)).upper()


BUTTON_MASK = STATUS_BIT_A0 | STATUS_BIT_A1 | STATUS_BIT_B0 | STATUS_BIT_B1


def _is_press_status(status: int) -> bool:
    """Press telegrams have Energy Bow bit set."""
    return bool(status & STATUS_BIT_ENERGY_BOW)


def _button_mask(payload: bytes) -> int:
    """Return button bits from status byte in LEN=9 telegram."""
    if len(payload) < 5:
        return 0
    return payload[4] & BUTTON_MASK
