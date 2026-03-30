"""Constants for EnOcean BLE integration."""

from __future__ import annotations

DOMAIN = "enocean_ble"
INTEGRATION_NAME = "PTM 215B/PTM 216B"
PLATFORMS = ["event"]

CONF_MAC_ADDRESS = "mac_address"
CONF_SECURITY_KEY = "security_key"

ENOCEAN_MANUFACTURER_ID = 0x03DA
ENOCEAN_MAC_PREFIX = "E2:15:"

EVENT_BUTTON_ACTION = "enocean_ble_button_action"
SIGNAL_BUTTON_EVENT = "enocean_ble_button_event_{entry_id}"

ATTR_BUTTON = "button"
ATTR_EVENT_TYPE = "event_type"
ATTR_RSSI = "rssi"
ATTR_SEQUENCE_COUNTER = "sequence_counter"
ATTR_MAC_ADDRESS = "mac_address"

SUPPORTED_BUTTONS = {"A0", "A1", "B0", "B1"}
SUPPORTED_EVENT_TYPES = {"press", "release", "long_press", "long_release"}

DATA_TELEGRAM_MIN_LENGTH = 9
MIC_LENGTH = 4
LONG_PRESS_SECONDS = 0.7

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
