## [HACS] EnOcean BLE — native support for PTM 215B / PTM 216B energy-harvesting switches

Hi everyone,

I just published **EnOcean BLE** on HACS — a custom integration for EnOcean BLE energy-harvesting wall switches (PTM 215B / PTM 216B).

These are the kinetic, battery-free switches that generate power from the button press itself. No wiring, no batteries — ever. They communicate over standard BLE 2.4 GHz.

---

### Already using these switches in another ecosystem?

PTM 215B/216B switches are the hardware core behind several commercial ecosystems. If you're running any of the following and want to bring your switches into Home Assistant — this integration is for you:

- **Casambi** — AIMOTION Switch 55, Tunto Wireless Switch, Kopp Blue-control and others use PTM 215B/216B as their kinetic transmitter
- **ABB free@home** — Busch-Jaeger 6716 UBT Smart Switch insert
- **Niko Home Control** — Niko Dimmer Switch Bluetooth
- **Feller EDIZIOdue** (Switzerland) — Feller BLE Funktaster (single and double rocker)
- **Eltako** — FTE215BLE wireless pushbutton
- **Vimar By-me / View** — Vimar 03925 4-button BLE device
- **Hytronik** — HBES01 kinetic wall switch

The switches themselves are not locked to their original ecosystem at the radio level — this integration communicates directly with the PTM 215B/216B BLE module, independently of any gateway or hub.

> **Note:** you may need to factory-reset the switch if it was previously configured with a custom security key by the original ecosystem. See the README for the reset procedure.

---

### What it does

- Bluetooth auto-discovery + guided commissioning flow (no YAML, no manual key entry)
- Secure telegram parsing with AES-128 MIC verification
- 4 event entities (A0, A1, B0, B1) + 4 sensor entities per device
- Handles BLE packet loss gracefully: detects lost press/release, fires synthetic events when appropriate

### Event model

| Layer | Events | When to use |
|---|---|---|
| Simple (guaranteed) | `single_press` | Toggle, scene, one-shot |
| Advanced (best-effort) | `press`, `release`, `long_press`, `long_release` | On/off by gesture, dimming |
| Safety net | `release_timeout`, `orphan_release` | Automation cleanup on packet loss |

`single_press` fires immediately on the press telegram — robust to a lost release. If the press is lost in BLE, it fires on a coherent orphan release (sequence gap == 2). Use one mode per button; do not mix `single_press` with advanced events.

---

### Supported hardware

Any wall switch built around the **EnOcean PTM 215B or PTM 216B** module. See the README for the full confirmed product list.

> Not for sub-1 GHz EnOcean switches (868/902 MHz PTM 210/215) or Zigbee Green Power (PTM 215Z/216Z). BLE 2.4 GHz only.

---

### Quick example — simple toggle

```yaml
alias: EnOcean A0 - Toggle light
mode: single
triggers:
  - trigger: state
    entity_id: sensor.my_switch_a0_event
    to: single_press
actions:
  - action: light.toggle
    target:
      entity_id: light.living_room
```

---

### Installation

HACS → Integrations → Custom repositories → add `https://github.com/Superkikim/enocean-ble`, category: Integration.

Or search **EnOcean BLE** directly in HACS if it's already indexed.

---

### Links

- Documentation (EN / DE / ES / FR / IT / PT): https://nexus-prod.dev
- GitHub: https://github.com/Superkikim/enocean-ble
- Issues / feedback: https://github.com/Superkikim/enocean-ble/issues

Happy to answer questions. If you have one of these switches and hit a problem, open an issue with your device model and I'll look into it.
