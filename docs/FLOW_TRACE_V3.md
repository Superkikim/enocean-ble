# FLOW_TRACE_V3

## Scope

This instrumentation adds debug-only correlation for config flow lifecycle and user-abandon intent.
No commissioning workflow decision logic is changed.

## Core/Frontend Evidence Used for Classification

1. Core REST abort path
   - File: `homeassistant/components/config/config_entries.py`
   - Class: `ConfigManagerFlowResourceView`
   - Route: `/api/config/config_entries/flow/{flow_id}`
   - Behavior: inherits `delete()` from `FlowManagerResourceView`.
   - Source: https://raw.githubusercontent.com/home-assistant/core/dev/homeassistant/components/config/config_entries.py
2. Core flow manager delete behavior
   - File: `homeassistant/helpers/data_entry_flow.py`
   - Class: `FlowManagerResourceView`
   - Method: `delete(self, request, flow_id)` -> `self._flow_mgr.async_abort(flow_id)`.
   - Source: https://raw.githubusercontent.com/home-assistant/core/dev/homeassistant/helpers/data_entry_flow.py
3. Core progress event
   - File: `homeassistant/data_entry_flow.py`
   - Constant: `EVENT_DATA_ENTRY_FLOW_PROGRESSED = "data_entry_flow_progressed"`.
   - Method: `FlowHandler.async_notify_flow_changed()` fires this event.
   - Source: https://raw.githubusercontent.com/home-assistant/core/dev/homeassistant/data_entry_flow.py
4. Frontend explicit delete call
   - File: `frontend/src/data/config_flow.ts`
   - Function: `deleteConfigFlow(...)` -> `hass.callApi("DELETE", "config/config_entries/flow/${flowId}")`.
   - Source: https://raw.githubusercontent.com/home-assistant/frontend/dev/src/data/config_flow.ts
5. Frontend config-flow dialog wiring
   - File: `frontend/src/dialogs/config-flow/show-dialog-config-flow.ts`
   - The dialog wiring passes `deleteFlow: deleteConfigFlow` to generic data-entry dialog handling.
   - Source: https://raw.githubusercontent.com/home-assistant/frontend/dev/src/dialogs/config-flow/show-dialog-config-flow.ts

## Limits (What We Can and Cannot Prove)

1. We can prove explicit abort when we observe flow progress state indicating abort for the same `flow_id`.
2. We cannot prove a concrete click target ("X", back button, outside click) from backend events alone.
   - Reason: backend only sees flow lifecycle/progress events, not UI click semantics.
3. If we observe flow progression for this `flow_id` and then flow removal without `create_entry`, we only classify as `USER_INTENT_UI_CLOSE_SUSPECTED` (medium confidence), never as a hard fact.
4. If no reliable UI-side signal exists, classification remains `TERMINATION_CAUSE_UNKNOWN` (low confidence).

## Signal -> Interpretation

| Observed signal | Inferred cause | Confidence |
|---|---|---|
| `data_entry_flow_progressed` for same `flow_id` with abort result | `USER_INTENT_ABORT_EXPLICIT` | high |
| UI flow progression observed, then no more progression, then `FLOW_REMOVED` without `FLOW_CREATE_ENTRY` | `USER_INTENT_UI_CLOSE_SUSPECTED` | medium |
| `FLOW_REMOVED` without `FLOW_CREATE_ENTRY` and no reliable UI abort/close signal | `TERMINATION_CAUSE_UNKNOWN` | low |

## Example Logs

### 1) Explicit user abort

```text
[ENOCEAN_FLOW] FLOW_TRACE_V3 event=UI_FLOW_PROGRESS_OBSERVED flow_id=abc123 mac=AA:BB:CC:DD:EE:FF step=bluetooth_confirm monotonic_ts=123.400 delta_stage_ms=... delta_last_seen_ms=... note=Observed data_entry_flow_progressed event for this flow. result_type=abort reason=user_aborted
[ENOCEAN_FLOW] FLOW_TRACE_V3 event=USER_INTENT_ABORT_EXPLICIT flow_id=abc123 mac=AA:BB:CC:DD:EE:FF step=bluetooth_confirm monotonic_ts=123.401 delta_stage_ms=... delta_last_seen_ms=... note=Explicit abort observed on flow progress channel. confidence=high reason=user_aborted
[ENOCEAN_FLOW] FLOW_TRACE_V3 event=FLOW_REMOVED flow_id=abc123 mac=AA:BB:CC:DD:EE:FF step=commissioning_hold_2 monotonic_ts=123.700 delta_stage_ms=... delta_last_seen_ms=... note=Flow removed by Home Assistant flow manager. has_entry=False ...
[ENOCEAN_FLOW] FLOW_TRACE_V3 event=FLOW_TERMINATED_WITHOUT_ENTRY flow_id=abc123 mac=AA:BB:CC:DD:EE:FF step=commissioning_hold_2 monotonic_ts=123.701 delta_stage_ms=... delta_last_seen_ms=... note=Flow terminated without creating an entry after explicit abort. cause=USER_INTENT_ABORT_EXPLICIT confidence=high
```

### 2) UI close/navigation suspected (no explicit abort)

```text
[ENOCEAN_FLOW] FLOW_TRACE_V3 event=UI_FLOW_PROGRESS_OBSERVED flow_id=abc123 mac=AA:BB:CC:DD:EE:FF step=commissioning_hold_1 ...
[ENOCEAN_FLOW] FLOW_TRACE_V3 event=FLOW_REMOVED flow_id=abc123 mac=AA:BB:CC:DD:EE:FF step=commissioning_click_short ...
[ENOCEAN_FLOW] FLOW_TRACE_V3 event=USER_INTENT_UI_CLOSE_SUSPECTED flow_id=abc123 mac=AA:BB:CC:DD:EE:FF step=commissioning_click_short ... note=UI progression disappeared before removal, close/navigation suspected. confidence=medium silence_ms=2450.0
[ENOCEAN_FLOW] FLOW_TRACE_V3 event=FLOW_TERMINATED_WITHOUT_ENTRY flow_id=abc123 mac=AA:BB:CC:DD:EE:FF step=commissioning_click_short ... cause=USER_INTENT_UI_CLOSE_SUSPECTED confidence=medium
```

### 3) Technical timeout without reliable user-abandon evidence

```text
[ENOCEAN_FLOW] FLOW_TRACE_V3 event=FLOW_STAGE_TIMEOUT flow_id=abc123 mac=AA:BB:CC:DD:EE:FF step=commissioning_release_2 ...
[ENOCEAN_FLOW] FLOW_TRACE_V3 event=FLOW_STAGE_SUMMARY flow_id=abc123 mac=AA:BB:CC:DD:EE:FF step=commissioning_release_2 ... total_seen=... accepted=... rejected_by_reason=... duplicates=... last_payload_ts=...
[ENOCEAN_FLOW] FLOW_TRACE_V3 event=FLOW_REMOVED flow_id=abc123 mac=AA:BB:CC:DD:EE:FF step=commissioning_release_2 ...
[ENOCEAN_FLOW] FLOW_TRACE_V3 event=TERMINATION_CAUSE_UNKNOWN flow_id=abc123 mac=AA:BB:CC:DD:EE:FF step=commissioning_release_2 ... confidence=low
[ENOCEAN_FLOW] FLOW_TRACE_V3 event=FLOW_TERMINATED_WITHOUT_ENTRY flow_id=abc123 mac=AA:BB:CC:DD:EE:FF step=commissioning_release_2 ... cause=TERMINATION_CAUSE_UNKNOWN confidence=low
```

## Reproducible Validation Procedure

1. Enable debug logs for `custom_components.enocean_ble`.
2. Start a new BLE commissioning flow and note `flow_id` from `FLOW_CREATED`.
3. Explicit abort scenario:
   - Start flow, then trigger explicit abort from UI.
   - Expect `USER_INTENT_ABORT_EXPLICIT` followed by `FLOW_TERMINATED_WITHOUT_ENTRY` with `cause=USER_INTENT_ABORT_EXPLICIT`.
4. UI close/navigation scenario:
   - Start flow, let progress events occur, close/navigate away without explicit abort.
   - Expect `USER_INTENT_UI_CLOSE_SUSPECTED` and terminal `FLOW_TERMINATED_WITHOUT_ENTRY` with medium confidence.
5. Technical timeout scenario:
   - Keep flow alive but do not provide expected BLE telegram.
   - Expect `FLOW_STAGE_TIMEOUT`.
   - On flow removal without explicit UI abort proof, expect `TERMINATION_CAUSE_UNKNOWN`.
6. Nominal success scenario:
   - Complete commissioning until create entry.
   - Expect `FLOW_CREATE_ENTRY`.
   - On final removal/cleanup, no abandon-cause terminal logs.
