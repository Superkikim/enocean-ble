# EnOcean BLE (PTM 215B/PTM 216B) for Home Assistant

`enocean_ble` is a Home Assistant custom integration for EnOcean BLE
energy-harvesting switches (PTM 215B/PTM 216B).

It provides:
- Bluetooth discovery + guided commissioning flow
- Secure telegram parsing (MIC verification)
- Button events as native Home Assistant `event` entities

## Supported Devices

- EnOcean PTM 215B
- EnOcean PTM 216B

## Installation

### HACS (recommended)
1. HACS -> `Integrations` -> `...` -> `Custom repositories`
2. Add this repository URL, category: `Integration`
3. Install `EnOcean BLE`
4. Restart Home Assistant

### Manual
1. Copy [`custom_components/enocean_ble`](custom_components/enocean_ble) to your HA `custom_components` directory
2. Restart Home Assistant
3. Settings -> Devices & Services -> `Add Integration` -> `EnOcean BLE`

## Add Your Device

1. Click `Add` when the switch appears in Bluetooth discovery.
2. Follow the sequence on button 1:
   - hold for about 7 seconds,
   - press briefly,
   - hold again for about 7 seconds.
3. When the confirmation screen appears, press another button (not button 1) to exit commissioning mode.
4. Click `Submit`.

Notes:
- If the switch is already in commissioning mode, progress can complete almost immediately.
- After success, press another button to ensure the switch exits commissioning mode.

## Events

The integration creates:
- 4 event entities: `A0`, `A1`, `B0`, `B1`
- 4 sensor entities: `A0 event`, `A1 event`, `B0 event`, `B1 event`

### Event types

The integration exposes three layers of events:

| Layer | Events | When to use |
|---|---|---|
| **RAW** | `press`, `release`, `orphan_release`, `release_timeout` | Advanced automations requiring full control |
| **CALCULÉS** (best-effort) | `long_press`, `long_release` | Dimming and hold-to-act patterns |
| **UX** | `single_press` | Simple on/off — most reliable |

**Definitions:**

- `press` — press telegram received from the device.
- `release` — release telegram received after a known `press`.
- `orphan_release` — release telegram received without a prior `press` (press lost in BLE). Fires `single_press` too if the gap is consistent with one lost telegram (reliable for single-button use without counter wrap).
- `release_timeout` — no release received within 8 seconds of a press. Technical fallback, not a real release.
- `long_press` — press held for more than 1.2 s without a release (best-effort).
- `long_release` — release received after a `long_press` (best-effort).
- `single_press` — fires immediately on the first valid signal of an interaction:
  - on `press`, or
  - on a coherent `orphan_release` (press lost, sequence gap == 2)

  Fires once per interaction, including long press cycles — use in simple mode only (see Usage rules below).

**Implicit cycle end rule:** any new event received for a button cancels the pending `release_timeout` timer and resets that button's state. In practice, starting a new press while the previous one is still "open" (release was lost) is handled automatically.

### Usage rules

Choose **one mode per button** — do not mix `single_press` with advanced events on the same button.

| Mode | Triggers to use | Reliability | Typical use |
|---|---|---|---|
| **Simple** | `single_press` only | Guaranteed | Toggle, scene, one-shot |
| **Advanced** | `press`, `release`, `long_press`, `long_release`, `release_timeout` | Best-effort | On/off by gesture, dimming |

> **Do not** use `single_press` on a button that also uses advanced events.
>
> **Why:** `single_press` fires immediately on press, before the press duration is known.
> If the button also uses advanced event triggers (`long_press`, `long_release`, etc.),
> `single_press` fires on **every** press — including long ones — creating unintended triggers
> alongside `long_press`.
>
> **Reliability:** `single_press` is robust to both telegram losses:
> - **Lost press** → fires via `orphan_release` coherence (sequence gap == 2)
> - **Lost release** → already fired on press; the lost release has no effect

Event data includes:
- `mac_address`
- `rssi`
- `sequence_counter`
- `button` (`A0`/`A1`/`B0`/`B1`)
- `event_type` (the event name)

Home Assistant event trigger:
- `enocean_ble_button_event` (recommended)
- `enocean_ble_button_action` (legacy, kept for compatibility)

## Usage Examples

### Example 1 — Simple toggle (guaranteed)

`single_press` fires immediately on the press telegram — robust to a lost release.
If the press is lost, it fires on a coherent orphan release (sequence gap == 2).
It fires on every press, including long ones — use in simple mode only
(do not combine with advanced events on the same button).

```yaml
alias: EnOcean A0 - Toggle light
mode: single
triggers:
  - trigger: state
    entity_id: sensor.nord_top_a0_event
    to: single_press
actions:
  - action: light.toggle
    target:
      entity_id: light.living_room
```

### Example 2 — Advanced on/off by gesture (not guaranteed)

Trigger on `press`, then wait for the next meaningful signal — first one wins.
Short press (`release` arrives first) turns the light on.
Long press (`long_press` arrives first, after 1.2 s) turns it off.
A new press while waiting cancels and restarts (`mode: restart` — Rule 3).
`release_timeout` terminates the automation cleanly if the release is lost.

> **Not guaranteed:** if the press telegram is lost, the automation never starts.
> If the release is lost on a short press, `long_press` fires at 1.2 s and the light
> turns off instead — accepted limitation in advanced mode.

```yaml
alias: EnOcean A1 - On/Off (advanced)
mode: restart
triggers:
  - trigger: state
    entity_id: sensor.nord_top_a1_event
    to: press
actions:
  - wait_for_trigger:
      - trigger: state
        entity_id: sensor.nord_top_a1_event
        to: release
        id: short
      - trigger: state
        entity_id: sensor.nord_top_a1_event
        to: long_press
        id: long
      - trigger: state
        entity_id: sensor.nord_top_a1_event
        to: release_timeout
        id: timeout
    timeout: "00:00:15"
    continue_on_timeout: false
  - choose:
      - conditions:
          - condition: template
            value_template: "{{ wait.trigger is not none and wait.trigger.id == 'short' }}"
        sequence:
          - action: light.turn_on
            target:
              entity_id: light.living_room
      - conditions:
          - condition: template
            value_template: "{{ wait.trigger is not none and wait.trigger.id == 'long' }}"
        sequence:
          - action: light.turn_off
            target:
              entity_id: light.living_room
```

### Example 3 — Dimming (hold to dim, release to stop, not guaranteed)

Hold B0 to dim up, hold B1 to dim down. Three events can stop the transition:
- `long_release` — normal release received
- `release_timeout` — release lost in BLE (fires after 8 s)
- `press` — any new press on the same button immediately stops the current transition
  (new interaction starts, `mode: restart` cancels the running sequence)

> **Not guaranteed:** `long_press` requires holding for 1.2 s and receiving the BLE release.
> `release_timeout` covers the lost-release case but fires after 8 s.

```yaml
alias: EnOcean B0/B1 - Dimming
mode: restart
triggers:
  - trigger: state
    entity_id: sensor.nord_top_b0_event
    to: press
    id: b0_stop
  - trigger: state
    entity_id: sensor.nord_top_b0_event
    to: long_press
    id: b0_up
  - trigger: state
    entity_id: sensor.nord_top_b0_event
    to: long_release
    id: b0_stop
  - trigger: state
    entity_id: sensor.nord_top_b0_event
    to: release_timeout
    id: b0_stop
  - trigger: state
    entity_id: sensor.nord_top_b1_event
    to: press
    id: b1_stop
  - trigger: state
    entity_id: sensor.nord_top_b1_event
    to: long_press
    id: b1_down
  - trigger: state
    entity_id: sensor.nord_top_b1_event
    to: long_release
    id: b1_stop
  - trigger: state
    entity_id: sensor.nord_top_b1_event
    to: release_timeout
    id: b1_stop
actions:
  - choose:
      - conditions:
          - condition: trigger
            id: b0_up
        sequence:
          - action: light.turn_on
            target:
              entity_id: light.living_room
            data:
              brightness_pct: 100
              transition: 8
      - conditions:
          - condition: trigger
            id: b0_stop
        sequence:
          - action: light.turn_on
            target:
              entity_id: light.living_room
            data:
              brightness: "{{ state_attr('light.living_room', 'brightness') | int }}"
              transition: 0
      - conditions:
          - condition: trigger
            id: b1_down
        sequence:
          - action: light.turn_on
            target:
              entity_id: light.living_room
            data:
              brightness_pct: 1
              transition: 8
      - conditions:
          - condition: trigger
            id: b1_stop
        sequence:
          - action: light.turn_on
            target:
              entity_id: light.living_room
            data:
              brightness: "{{ state_attr('light.living_room', 'brightness') | int }}"
              transition: 0
```

> `long_press` and `long_release` are best-effort: they depend on the BLE release telegram being received. If the release is lost, `release_timeout` fires after 8 seconds instead of `long_release`. The "freeze at current brightness" approach works with most Zigbee/Z-Wave/Hue integrations; behavior during transition depends on whether the light driver reports current or target brightness.

## Troubleshooting

- Device re-adds immediately after deletion:
  the switch is likely still in commissioning mode and keeps sending `LEN=26`.
- No button events:
  verify BLE reception and that commissioning completed successfully.
- Auto-commissioning sequence never works:
  device may have commissioning mode disabled by prior configuration; try factory reset.
- Intermittent events:
  check distance/RSSI/interference.
- Occasional missed press:
  can happen on 2.4 GHz BLE in real environments (interference, attenuation, collisions). This is inherent to radio communication and not always a software defect.

## Migration / Factory Reset

If the switch has been used in another ecosystem, commissioning in Home Assistant can fail if active key/settings no longer match what you expect.

For example, with Casambi, the switch may not show up in Home Assistant. In that case, perform a factory reset. You can then remove the switch from the Casambi app by swiping it to the left and pressing Delete.
You can later add it back to the Casambi network. This was tested during development.

> [!WARNING]
> Disclaimer (OEM setups): some manufacturers/integrators can customize commissioning and radio behavior via NFC (for example commissioning mode behavior, addressing/security parameters, or other module settings).
> A factory reset restores EnOcean default module settings.
> After reset, re-joining the original OEM ecosystem may require re-provisioning, and in some setups it may no longer be possible without OEM tools/process.

> [!WARNING]
> If auto-commissioning never starts (or never yields a commissioning telegram), the device may have radio commissioning disabled by prior NFC/OEM configuration.

In that case, perform a factory reset on the switch module:
1. Remove rocker and housing to access module contacts.
2. Press `A0 + A1 + B0 + B1` together.
3. While holding those contacts, press the energy bow.
4. Keep the energy bow pressed for at least 10 seconds.
5. Release and retry commissioning.

![PTM 21xB contact map and energy bow](assets/docs/ptm21xb_contacts_readme.png)

Practical tip:
- This is physically tricky. A common trick is to hold the 4 contacts with one hand (or a small non-conductive tool) and press/hold the energy bow with the other hand.

## Compatibility

Tested with:
- Feller EDIZIOdue BLE Switch (user-tested in this project)

Compatibility assumption:
- In general, PTM 215B/PTM 216B-based BLE switches should work with this integration.
- However, compatibility is not mathematically guaranteed if product NFC/BLE settings were customized.

Important:
- Not every product labeled "EnOcean" is BLE.
- This integration targets BLE telegrams in the 2.4 GHz band from PTM 215B/PTM 216B family devices.
- Sub-GHz EnOcean products (e.g. 868/902 MHz) are out of scope for this integration.

### Wall switches integrating EnOcean PTM 215B or PTM 216B

**Twelve distinct switch models from ten manufacturers** are confirmed to integrate EnOcean's BLE energy-harvesting modules PTM 215B or PTM 216B. The PTM 215B (launched ~2018) is now marked "not recommended for new designs" and is being superseded by the PTM 216B (announced January 2024), which offers doubled radio transmission power via the newer ECO 260 harvester. Both modules share the same 40×40×11.2 mm form factor, enabling drop-in replacement. Most major European switch brands (Gira, Jung, Berker, Merten) do **not** manufacture their own PTM 215B/216B switch products — they only supply compatible decorative frames for EnOcean's own Easyfit switches.

#### Confirmed products with explicit module identification

Every product below has the PTM 215B or PTM 216B **explicitly named** in official manufacturer documentation, datasheets, installer manuals, or authoritative EnOcean partner pages.

| Manufacturer | Model | Module(s) | Datasheet / User Guide |
|---|---|---|---|
| EnOcean (Germany) | EWSSB — Easyfit Single Rocker Wall Switch, EU 55 mm | PTM 215B (older rev) / PTM 216B (rev DD) | [EWSxB Datasheet (PDF)](https://www.enocean.com/wp-content/uploads/downloads-produkte/en/products/enocean_modules_24ghz_ble/easyfit-single-double-rocker-wall-switch-for-ble-ewssb-ewsdb/data-sheet-pdf/EWSxB_Datasheet.pdf) · [User Manual rev DD (PDF)](https://www.enocean.com/wp-content/uploads/downloads-produkte/en/products/enocean_modules_24ghz_ble/easyfit-single-double-rocker-wall-switch-for-ble-ewssb-ewsdb/user-manual-pdf/EWSxB_DD_User_Manual.pdf) |
| EnOcean (Germany) | EWSDB — Easyfit Double Rocker Wall Switch, EU 55 mm | PTM 215B (older rev) / PTM 216B (rev DD) | Same as EWSSB above |
| EnOcean (Germany) | ESRPB — Easyfit Single Rocker Pad, US Decora style | PTM 216B | [Product page](https://www.enocean.com/en/product/easyfit-single-double-rocker-pad-for-ble-esrpb-edrpb/) |
| EnOcean (Germany) | EDRPB — Easyfit Double Rocker Pad, US Decora style | PTM 216B | Same as ESRPB above |
| Feller (Switzerland) | 4122.1.S.F — EDIZIOdue BLE Funktaster, single rocker, 2-channel | PTM 215B | [Online catalog](https://online-katalog.feller.ch/kat_details.php?fnr=4122.1.S.F.67) |
| Feller (Switzerland) | 4122.2.S.F — EDIZIOdue BLE Funktaster, double rocker, 4-channel | PTM 215B | [Online catalog](https://online-katalog.feller.ch/kat_details.php?fnr=4122.2.S.FMI.67) |
| Eltako (Germany) | FTE215BLE — Wireless pushbutton insert, BLE | PTM 215B | [Datasheet (PDF)](https://www.eltako.com/fileadmin/downloads/en/_datasheets/Datasheet_FTE.pdf) · [Product page](https://www.eltako.com/en/product/professional-standard-en/accessories-professional-standard/fte215ble/) |
| Vimar (Italy) | 03925 — Bluetooth Low Energy RF 4-button device | PTM 215B | [Installer manual (PDF)](https://www.vimar.com/irj/go/km/docs/z_catalogo/DOCUMENT/03925IEN.80268.pdf) · [Product page](https://www.vimar.com/en/int/catalog/product/index/code/03925) |
| Hytronik (China) | HBES01 — Wireless BLE kinetic wall switch, EU 55 mm | PTM 215B | [Datasheet (PDF)](https://hytronik.com/system-level-components/switch-enocean-hbes01-b/switch-enocean-hbes01-b.pdf) · [Product page](https://hytronik.com/product/switch-enocean-hbes01-b) |
| AIMOTION (Germany) | Switch 55 (1051xx / 1052xx) — Casambi BLE wall switch | PTM 216B | [Datasheet (PDF)](https://casambi-aimotion.de/wp-content/uploads/2025/03/AIMOTION_1051_1052_Casambi_EnOcean_Switch_55_v.3.7.pdf) · [Product page](https://casambi-aimotion.de/en/produkt/switch-55-white/) |
| Niko (Belgium) | Dimmer switch, Bluetooth® — wireless dimmer rocker | PTM 216B | [Niko product page](https://www.niko.eu/en/products/wireless-controls/niko-dimmer-switch-enocean-productmodel-niko-785fb59a-c90e-5349-a30b-35fc36009b20) · [EnOcean partner page](https://www.enocean.com/en/batteryfree/niko-dimmer-switch-bluetooth/) |
| Kopp (Germany) | Blue-control Wandschaltermodul (867001011) — BT Mesh wall switch | PTM 215B | [Product page](https://produkte.kopp.eu/de/produkt/blue-control-energieautarkes-bluetooth-wandschaltermodul-mit-montagerahmen-2/) |

#### Products with strong indirect evidence but no explicit module naming

These switches use BLE 2.4 GHz energy harvesting with NFC and AES-128 — technology exclusive to the PTM 215B/216B — but their manufacturers do not publicly name the internal EnOcean module in accessible documentation.

| Manufacturer | Model | Likely Module | Datasheet / User Guide |
|---|---|---|---|
| Busch-Jaeger / ABB (Germany) | 6716 UBT — BLE Smart Switch insert | PTM 215B (all specs match; released 2022, before PTM 216B existed) | [Product page](https://www.busch-jaeger.de/en/online-catalogue/detail/2CKA006710A0015) · [Product manual (PDF)](https://www.busch-jaeger.de/files/files_ONLINE/BLE_Smart%20Switch_BJE_DE_18.08.2022.pdf) |
| Häfele (Germany) | 850.00.025 — BLE Single Rocker Wall Switch, US Decora | PTM 215B (FCC filing references PTM 215B user manual) | [Product page](https://www.hafele.com/us/en/product/wall-switch-ble-single-rocker-white-usa/85000025/) |
| Häfele (Germany) | 850.00.940 / 850.00.944 — Battery-Free Wireless Wall Switch, US Decora (replaces 850.00.025/026) | PTM 215B or PTM 216B | [Product page (double)](https://www.hafele.com/us/en/product/double-rocker-kinetic-wall-switch-bluetooth-battery-free-wireless-connect-mesh/P-01956566/) |
| Retrotouch (UK) | Crystal EnOcean Smart Switch (02623 BLE variant) — glass rocker, 86 mm | PTM 215B or PTM 216B (EnOcean-certified partner) | [Manufacturer page](https://www.retrotouch.co.uk/enocean-wireless-kinetic-switches.html) · [EnOcean partner page](https://www.enocean.com/en/battery-free-products/retrotouch/) |
| Tunto (Finland) | Wireless Tunto Switch — designer BLE rocker | PTM 215B (transmit power 0.4 dBm matches PTM 215B spec exactly) | [Product page](https://www.tunto.com/product-page/enocean-switch) · [Casambi listing](https://casambi.com/ecosystem/tunto-enocean-switch/) |

#### Why so few products exist for these specific modules

The relatively short list reflects a critical distinction many buyers overlook. **The PTM 215B and PTM 216B are the BLE (Bluetooth Low Energy, 2.4 GHz) variants** of EnOcean's pushbutton transmitter module family. The vast majority of EnOcean-branded wall switches on the market — from well-known brands like Theben, NodOn, Peha, and Thermokon — use the **sub-1 GHz PTM 210 or PTM 215** (868/902 MHz EnOcean radio protocol) or the **PTM 215Z/216Z** (Zigbee Green Power). These are entirely different radio standards despite sharing the same physical form factor. Several "Friends of Hue" switches (from Senic, Gira, Jung, Berker) use PTM 215Z/215ZE for Zigbee Green Power, not BLE.

Major European switch brands like **Gira, Jung, Berker/Hager, and Merten/Schneider Electric** do not manufacture their own PTM 215B/216B switch inserts. Instead, their 55 mm decorative frames are compatible with EnOcean's own Easyfit EWSSB/EWSDB products. Similarly, brands like **Siemens, Legrand, Eaton, and WAGO** were searched extensively and have no confirmed PTM 215B/216B products. No Japanese, Korean, or Taiwanese manufacturers were found producing PTM 215B/216B switches.

#### The PTM 215B to PTM 216B transition is underway

The PTM 216B, announced at Light + Building 2024, delivers **more than double the radio transmission power** of the PTM 215B and supports **Bluetooth Long Range**. It uses the newer ECO 260 kinetic harvester while maintaining full mechanical backward compatibility. EnOcean's own Easyfit switches have already transitioned (revision DD uses PTM 216B), and AIMOTION's Switch 55 datasheet v3.7 (March 2025) confirms PTM 216B, having upgraded from PTM 215B in earlier versions. Niko's Bluetooth dimmer is also confirmed on PTM 216B. As PTM 215B stock depletes, all manufacturers are expected to migrate. The module-level datasheets are available from EnOcean: [PTM 215B datasheet](https://www.enocean.com/wp-content/uploads/downloads-produkte/en/products/enocean_modules_24ghz_ble/ptm-215b/data-sheet-pdf/PTM_215B_Datasheet.pdf) and [PTM 216B datasheet](https://www.enocean.com/wp-content/uploads/downloads-produkte/en/products/enocean_modules_24ghz_ble/ptm-216b/data-sheet-pdf/PTM-216B-Datasheet-1.pdf).

#### Conclusion

The PTM 215B/216B BLE ecosystem is concentrated around **10 confirmed manufacturers** with 12 distinct switch models — far fewer than the hundreds of products using EnOcean's older sub-1 GHz modules. EnOcean itself (via Easyfit), Feller, Eltako, Vimar, and Hytronik are the confirmed PTM 215B incumbents. AIMOTION and Niko represent the first wave of confirmed PTM 216B adopters alongside EnOcean's own updated Easyfit line. Five additional products from Busch-Jaeger, Häfele, Retrotouch, and Tunto show strong technical evidence of PTM 215B/216B use but lack explicit module identification in publicly available documentation. The market is actively transitioning to PTM 216B, and new product announcements using this module should accelerate through 2026.

## Security

- Device security keys are stored in config entries.
- Keys must never be logged in clear text.
- Telegram authentication uses AES-128 CCM MIC verification.

## Development

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements_dev.txt
```

Checks:

```bash
ruff check .
mypy custom_components tests
pytest -q
```

## References

- [PTM-215B User Manual](https://www.enocean.com/wp-content/uploads/downloads-produkte/en/products/enocean_modules_24ghz_ble/ptm-215b/user-manual-pdf/PTM-215B-User-Manual.pdf)
- [PTM-216B User Manual](https://www.enocean.com/wp-content/uploads/downloads-produkte/en/products/enocean_modules_24ghz_ble/ptm-216b/user-manual-pdf/PTM-216B-User-Manual-3.pdf)
- [`docs/README.md`](docs/README.md)
