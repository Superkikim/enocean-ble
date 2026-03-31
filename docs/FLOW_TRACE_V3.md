# FLOW_TRACE_V3

## Scope

`FLOW_TRACE_V3` is debug instrumentation for commissioning flow observability.

- No commissioning business logic change.
- Every trace line includes `flow_id`.
- Terminal removal without entry is explicitly logged.

## Implemented Event Set

Lifecycle and stage events currently emitted by the integration:

- `FLOW_CREATED`
- `FLOW_STAGE_ENTER`
- `FLOW_PAYLOAD_CANDIDATE`
- `FLOW_STAGE_EXIT`
- `FLOW_STAGE_SUMMARY`
- `FLOW_STAGE_TIMEOUT`
- `FLOW_STAGE_ERROR`
- `FLOW_CONFIRM_SHOWN`
- `FLOW_USER_ADD_CONFIRMED`
- `FLOW_CREATE_ENTRY`
- `FLOW_REMOVED`
- `FLOW_TERMINATED_WITHOUT_ENTRY`

## Common Correlation Fields

All `FLOW_TRACE_V3` lines include:

- `flow_id`
- `mac`
- `step`
- `monotonic_ts`
- `delta_stage_ms`
- `delta_last_seen_ms`
- `note`

Payload candidate lines also include:

- `payload_hex`
- `len`
- `status`
- `inferred_event`
- `button_mask`
- `decision`
- `reject_reason`
- `payload_ts`

## Stage Summary Fields

`FLOW_STAGE_SUMMARY` contains:

- `total_seen`
- `accepted`
- `rejected_by_reason`
- `duplicates`
- `last_payload_ts`

## Terminal Cause Classification (Current)

Current implementation guarantees only one safe terminal classification when flow is removed without entry:

- `cause=UNKNOWN`
- `confidence=low`

This is logged as:

- `FLOW_TERMINATED_WITHOUT_ENTRY`

## Why Abort/User-Intent Is Not Asserted

The integration does not currently consume or persist enough UI-side evidence to safely assert user intent (`X`, back navigation, dialog close, explicit delete) for all cases.

So the trace intentionally avoids false claims and logs unknown cause unless entry creation is confirmed.

## Example Logs

### Nominal success

```text
[ENOCEAN_FLOW] FLOW_TRACE_V3 event=FLOW_CREATED flow_id=... mac=... step=bluetooth ...
[ENOCEAN_FLOW] FLOW_TRACE_V3 event=FLOW_STAGE_ENTER flow_id=... mac=... step=commissioning ...
[ENOCEAN_FLOW] FLOW_TRACE_V3 event=FLOW_PAYLOAD_CANDIDATE flow_id=... mac=... step=commissioning ... len=26 decision=accepted ...
[ENOCEAN_FLOW] FLOW_TRACE_V3 event=FLOW_STAGE_EXIT flow_id=... mac=... step=commissioning ...
[ENOCEAN_FLOW] FLOW_TRACE_V3 event=FLOW_CONFIRM_SHOWN flow_id=... mac=... step=bluetooth_confirm ...
[ENOCEAN_FLOW] FLOW_TRACE_V3 event=FLOW_USER_ADD_CONFIRMED flow_id=... mac=... step=bluetooth_confirm ...
[ENOCEAN_FLOW] FLOW_TRACE_V3 event=FLOW_CREATE_ENTRY flow_id=... mac=... step=bluetooth_confirm ...
[ENOCEAN_FLOW] FLOW_TRACE_V3 event=FLOW_REMOVED flow_id=... mac=... has_entry=True ...
```

### Timeout/retry path (no entry)

```text
[ENOCEAN_FLOW] FLOW_TRACE_V3 event=FLOW_STAGE_TIMEOUT flow_id=... mac=... step=commissioning ...
[ENOCEAN_FLOW] FLOW_TRACE_V3 event=FLOW_STAGE_SUMMARY flow_id=... mac=... step=commissioning ...
[ENOCEAN_FLOW] FLOW_TRACE_V3 event=FLOW_REMOVED flow_id=... mac=... has_entry=False ...
[ENOCEAN_FLOW] FLOW_TRACE_V3 event=FLOW_TERMINATED_WITHOUT_ENTRY flow_id=... mac=... cause=UNKNOWN confidence=low ...
```
