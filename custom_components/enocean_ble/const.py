"""Constants for EnOcean BLE integration."""

from __future__ import annotations

DOMAIN = "enocean_ble"
INTEGRATION_NAME = "PTM 215B/PTM 216B"
PLATFORMS = ["event", "sensor"]

CONF_MAC_ADDRESS = "mac_address"
CONF_SECURITY_KEY = "security_key"

ENOCEAN_MANUFACTURER_ID = 0x03DA
ENOCEAN_MAC_PREFIX = "E2:15:"

EVENT_BUTTON_EVENT = "enocean_ble_button_event"
# Backward compatibility with existing automations.
EVENT_BUTTON_ACTION = "enocean_ble_button_action"
# One signal per button, so only the entities of that button receive its events.
SIGNAL_BUTTON_EVENT = "enocean_ble_button_event_{entry_id}_{button}"
# Diagnostic values of a switch changed (signal, last seen, receiver, lost messages).
SIGNAL_DEVICE_UPDATE = "enocean_ble_device_update_{entry_id}"

ATTR_BUTTON = "button"
ATTR_EVENT_TYPE = "event_type"
ATTR_RSSI = "rssi"
ATTR_SEQUENCE_COUNTER = "sequence_counter"
ATTR_MAC_ADDRESS = "mac_address"
# Bluetooth receiver (adapter or proxy) that delivered the telegram.
ATTR_RECEIVER = "receiver"
# hold_release: why the hold ended (release, timeout or next_telegram).
ATTR_REASON = "reason"
# raw_release: the press telegram of this click was not received.
ATTR_PRESS_LOST = "press_lost"

SUPPORTED_BUTTONS = {"A0", "A1", "B0", "B1"}
# Events of the Legacy button mode (versions before 2026.11), unchanged.
SUPPORTED_EVENT_TYPES = {
    "press", "release", "orphan_release", "release_timeout",
    "long_press", "long_release",
    "single_press",
}

# Button mode, set per switch (config entry option).
CONF_BUTTON_MODE = "button_mode"
MODE_SIMPLE = "simple"
MODE_SHORT_LONG = "short_long"
MODE_SHORT_HOLD = "short_hold"
# Switches added before 2026.11 keep the old events until the user picks a mode.
MODE_LEGACY = "legacy"
BUTTON_MODES = [MODE_SIMPLE, MODE_SHORT_LONG, MODE_SHORT_HOLD]

EVENT_SINGLE_PRESS = "single_press"
EVENT_SHORT_PRESS = "short_press"
EVENT_LONG_PRESS = "long_press"
EVENT_HOLD_PRESS = "hold_press"
EVENT_HOLD_RELEASE = "hold_release"
EVENT_RAW_PRESS = "raw_press"
EVENT_RAW_RELEASE = "raw_release"

MODE_EVENT_TYPES: dict[str, list[str]] = {
    MODE_SIMPLE: [EVENT_SINGLE_PRESS],
    MODE_SHORT_LONG: [EVENT_SHORT_PRESS, EVENT_LONG_PRESS],
    MODE_SHORT_HOLD: [EVENT_SHORT_PRESS, EVENT_HOLD_PRESS, EVENT_HOLD_RELEASE],
    MODE_LEGACY: sorted(SUPPORTED_EVENT_TYPES),
}
RAW_EVENT_TYPES = [EVENT_RAW_PRESS, EVENT_RAW_RELEASE]

HOLD_REASON_RELEASE = "release"
HOLD_REASON_TIMEOUT = "timeout"
HOLD_REASON_NEXT_TELEGRAM = "next_telegram"

# Short + long / Short + hold: a press held this long is a long press or a hold.
GESTURE_THRESHOLD_SECONDS = 1.0
# Lost messages: larger counter gaps mean Home Assistant was not running (or the
# switch was used elsewhere), not a reception problem; they are not counted.
MAX_COUNTED_GAP = 10

DATA_TELEGRAM_MIN_LENGTH = 9
MIC_LENGTH = 4
# Legacy mode long press.
LONG_PRESS_SECONDS = 1.2
# A hold without release ends after this time (release lost).
RELEASE_TIMEOUT_SECONDS = 8.0

# The last accepted sequence counter is stored, so replay protection survives restarts.
STORAGE_VERSION = 1
STORAGE_SAVE_DELAY_SECONDS = 5.0

STATUS_BIT_ENERGY_BOW = 0x01
STATUS_BIT_A0 = 0x02
STATUS_BIT_A1 = 0x04
STATUS_BIT_B0 = 0x08
STATUS_BIT_B1 = 0x10

BUTTON_BIT_TO_NAME = {
    STATUS_BIT_A0: "A0",
    STATUS_BIT_A1: "A1",
    STATUS_BIT_B0: "B0",
    STATUS_BIT_B1: "B1",
}

BUTTON_ENTITY_DESCRIPTIONS = {
    "A0": "A0",
    "A1": "A1",
    "B0": "B0",
    "B1": "B1",
}
