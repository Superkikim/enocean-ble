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
    STATUS_BIT_ENERGY_BOW,
)
from .parser import parse_commissioning_telegram

_LOGGER = logging.getLogger(__name__)
FLOW_TAG = "[ENOCEAN_FLOW]"
CANCEL_TRACE_TAG = "FLOW_CANCEL_TRACE"
FLOW_TRACE_TAG = "FLOW_TRACE_V3"

COMMISSIONING_TIMEOUT = 120.0


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
        self._last_filter_signature: tuple[str, str, str] | None = None

        self._stage_task: asyncio.Task[None] | None = None
        self._stage_error: str | None = None
        self._last_progress_next_step: str | None = None
        self._last_progress_transition_at: float = 0.0
        self._stage_started_monotonic: float = 0.0
        self._entry_created: bool = False
        self._terminal_cause_logged: bool = False
        self._flow_created_logged: bool = False
        self._active_stage_id: str | None = None
        self._stage_stats: dict[str, dict[str, Any]] = {}

    def async_remove(self) -> None:
        """Cleanup when flow is aborted/cancelled/finished by HA."""
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
        )
        _LOGGER.debug(
            "%s %s event=FLOW_REMOVED address=%s step=%s next=%s task_active=%s has_key=%s",
            FLOW_TAG,
            CANCEL_TRACE_TAG,
            self._pending_mac,
            current_step,
            self._last_progress_next_step,
            self._stage_task is not None and not self._stage_task.done(),
            self._pending_security_key is not None,
        )
        self._log_terminal_without_entry()
        self._cancel_stage_task(reason="flow_removed")

    async def async_step_bluetooth(self, discovery_info: BluetoothServiceInfoBleak) -> FlowResult:
        """Handle Bluetooth discovery and start commissioning."""
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
        _LOGGER.info(
            "%s DISCOVERED flow_id=%s mac=%s name=%s source=%s rssi=%s",
            FLOW_TAG,
            getattr(self, "flow_id", "unknown"),
            discovered_mac,
            discovery_info.name,
            discovery_info.source,
            discovery_info.rssi,
        )

        if not discovered_mac.startswith(ENOCEAN_MAC_PREFIX):
            return self.async_abort(reason="not_enocean_prefix")

        await self.async_set_unique_id(discovered_mac)
        self._abort_if_unique_id_configured()

        self._reset_progress_state(discovered_mac)
        self._pending_mac = discovered_mac
        self._pending_title = discovery_info.name or discovered_mac
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

        return await self.async_step_commissioning()

    async def async_step_commissioning(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Show commissioning instructions and wait for L26 telegram."""
        # If the commissioning telegram is already known (ex: cached discovery payload),
        # continue to the explicit user confirmation step.
        if self._pending_security_key is not None and self._stage_task is None:
            return await self.async_step_bluetooth_confirm()
        return await self._async_run_stage(
            step_id="commissioning",
            progress_action="waiting_commissioning",
            coro=self._async_stage_wait_commissioning,
            next_step_id="bluetooth_confirm",
        )

    async def async_step_bluetooth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Ask for explicit user confirmation before creating the entry."""
        if self._pending_mac is None or self._pending_security_key is None:
            return self.async_show_form(
                step_id="commissioning",
                errors={"base": "commissioning_not_detected"},
                description_placeholders={"name": self._pending_title or self._pending_mac or DOMAIN},
            )

        if user_input is None:
            self._trace_event(
                "FLOW_CONFIRM_SHOWN",
                step="bluetooth_confirm",
                note="Commissioning complete; waiting for explicit user confirmation.",
            )
            self._set_confirm_only()
            return self.async_show_form(
                step_id="bluetooth_confirm",
                description_placeholders={
                    "name": self._pending_title or self._pending_mac or DOMAIN,
                    "mac": self._pending_mac,
                },
            )

        self._trace_event(
            "FLOW_USER_ADD_CONFIRMED",
            step="bluetooth_confirm",
            note="User confirmed final add after commissioning success.",
        )
        _LOGGER.debug(
            "flow_commissioning_create_entry address=%s title=%s",
            self._pending_mac,
            self._pending_title,
        )
        _LOGGER.info(
            "%s ADD_CONFIRMED_CREATE_ENTRY flow_id=%s mac=%s title=%s",
            FLOW_TAG,
            getattr(self, "flow_id", "unknown"),
            self._pending_mac,
            self._pending_title,
        )
        self._entry_created = True
        self._trace_event(
            "FLOW_CREATE_ENTRY",
            step="bluetooth_confirm",
            note="Commissioning succeeded and config entry is being created.",
            title=self._pending_title or self._pending_mac or DOMAIN,
        )
        return self.async_create_entry(
            title=self._pending_title or self._pending_mac or DOMAIN,
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
                description_placeholders={"name": self._pending_title or self._pending_mac or DOMAIN},
            )

        try:
            self._stage_task.result()
        except TimeoutError:
            self._stage_error = "commissioning_not_detected"
            self._trace_event(
                "FLOW_STAGE_TIMEOUT",
                step=step_id,
                note="Stage timed out waiting for commissioning telegram.",
                error=self._stage_error,
            )
            _LOGGER.warning(
                "%s COMMISSIONING_TIMEOUT flow_id=%s mac=%s step=%s timeout_s=%s",
                FLOW_TAG,
                getattr(self, "flow_id", "unknown"),
                self._pending_mac,
                step_id,
                COMMISSIONING_TIMEOUT,
            )
        except ValueError as err:
            self._stage_error = "invalid_commissioning"
            self._trace_event(
                "FLOW_STAGE_ERROR",
                step=step_id,
                note="Stage failed because commissioning payload was invalid.",
                error=self._stage_error,
            )
            _LOGGER.error(
                "%s COMMISSIONING_ERROR flow_id=%s mac=%s step=%s error=%s",
                FLOW_TAG,
                getattr(self, "flow_id", "unknown"),
                self._pending_mac,
                step_id,
                err,
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
                description_placeholders={"name": self._pending_title or self._pending_mac or DOMAIN},
            )

        self._trace_event(
            "FLOW_STAGE_EXIT",
            step=step_id,
            note="Stage completed successfully.",
            next_step=next_step_id,
        )
        self._log_stage_summary(step_id=step_id)
        self._last_progress_next_step = next_step_id
        self._last_progress_transition_at = self.hass.loop.time()
        self._active_stage_id = None
        return self.async_show_progress_done(next_step_id=next_step_id)

    async def _async_stage_wait_commissioning(self) -> None:
        """Wait for L26 commissioning telegram with a generous timeout."""
        _LOGGER.debug(
            "%s COMMISSIONING start: waiting LEN=26 telegram timeout=%ss",
            FLOW_TAG,
            COMMISSIONING_TIMEOUT,
        )
        payload = await self._async_wait_for_payload_len(
            26,
            timeout=COMMISSIONING_TIMEOUT,
            stage_label="COMMISSIONING",
        )
        self._apply_commissioning_payload(payload)
        _LOGGER.debug("%s COMMISSIONING complete", FLOW_TAG)

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
            _LOGGER.warning(
                "%s COMMISSIONING_MAC_MISMATCH flow_id=%s mac=%s payload_mac=%s payload_mac_reversed=%s",
                FLOW_TAG,
                getattr(self, "flow_id", "unknown"),
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
        _LOGGER.info(
            "%s COMMISSIONING_READY flow_id=%s mac=%s sequence_counter=%s",
            FLOW_TAG,
            getattr(self, "flow_id", "unknown"),
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
        self._last_filter_signature = None
        self._last_progress_next_step = None
        self._last_progress_transition_at = 0.0
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
        if decision == "accepted":
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

    def _log_terminal_without_entry(self) -> None:
        """Log terminal event when flow is removed without entry creation."""
        if self._terminal_cause_logged:
            return
        self._terminal_cause_logged = True
        if self._entry_created:
            return
        self._trace_event(
            "FLOW_TERMINATED_WITHOUT_ENTRY",
            note="Flow removed without entry.",
            cause="UNKNOWN",
            confidence="low",
        )
        _LOGGER.warning(
            "%s FLOW_TERMINATED_WITHOUT_ENTRY flow_id=%s mac=%s cause=UNKNOWN confidence=low",
            FLOW_TAG,
            getattr(self, "flow_id", "unknown"),
            self._pending_mac,
        )


def _is_press_status(status: int) -> bool:
    return bool(status & STATUS_BIT_ENERGY_BOW)


def _button_mask(payload: bytes) -> int:
    return payload[4] & 0x1E


def _format_mac(hex6: str) -> str:
    return ":".join(hex6[i : i + 2].upper() for i in range(0, 12, 2))


def _reverse_mac_hex(hex6: str) -> str:
    pairs = [hex6[i : i + 2] for i in range(0, 12, 2)]
    return "".join(reversed(pairs))
