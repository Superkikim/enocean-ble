"""Parsers for EnOcean BLE onboarding blobs and telegram frames."""

from __future__ import annotations

import re
from dataclasses import dataclass

from .const import (
    BUTTON_BIT_TO_NAME,
    ENOCEAN_MAC_PREFIX,
    MIC_LENGTH,
    STATUS_BIT_ENERGY_BOW,
)
from .crypto import verify_mic

MAC_RE = re.compile(r"([0-9A-Fa-f]{2}(?::[0-9A-Fa-f]{2}){5})")
KEY_RE = re.compile(r"\b([0-9A-Fa-f]{32})\b")


@dataclass(slots=True, frozen=True)
class OnboardingData:
    """Normalized onboarding information extracted from NFC/QR payload."""

    mac_address: str
    security_key_hex: str


@dataclass(slots=True, frozen=True)
class ParsedTelegram:
    """Parsed EnOcean BLE data telegram."""

    sequence_counter: int
    buttons: tuple[str, ...]
    event_type: str


@dataclass(slots=True, frozen=True)
class ParsedCommissioningTelegram:
    """Parsed commissioning telegram payload (manufacturer data only)."""

    sequence_counter: int
    security_key_hex: str
    static_source_address_hex: str


def parse_onboarding_blob(raw: str) -> OnboardingData:
    """Extract MAC and AES-128 key from NFC/QR raw data."""
    mac_match = MAC_RE.search(raw)
    key_match = KEY_RE.search(raw)

    if mac_match is None:
        raise ValueError("No MAC address found in onboarding payload")
    if key_match is None:
        raise ValueError("No 128-bit security key found in onboarding payload")

    mac_address = mac_match.group(1).upper()
    if not mac_address.startswith(ENOCEAN_MAC_PREFIX):
        raise ValueError("MAC prefix is not EnOcean E2:15")

    return OnboardingData(mac_address=mac_address, security_key_hex=key_match.group(1).lower())


def parse_data_telegram(
    telegram: bytes,
    *,
    mac_address: str,
    security_key_hex: str,
) -> ParsedTelegram:
    """Parse and verify an EnOcean BLE telegram with AES-128 MIC.

    Telegram layout:
    - sequence counter: 4 bytes LE
    - payload: >=1 byte (switch status + optional bytes)
    - MIC: 4 bytes
    """
    if len(telegram) < 5 + MIC_LENGTH:
        raise ValueError("EnOcean BLE telegram too short")

    sequence_counter = int.from_bytes(telegram[0:4], byteorder="little")
    payload = telegram[4:-MIC_LENGTH]
    mic = telegram[-MIC_LENGTH:]

    if not payload:
        raise ValueError("EnOcean BLE telegram payload missing")

    key = bytes.fromhex(security_key_hex)
    # Source address in nonce must be little-endian as specified by PTM215B/PTM216B manuals.
    mac = bytes.fromhex(mac_address.replace(":", ""))[::-1]

    if not verify_mic(
        security_key=key,
        mac_address_bytes=mac,
        sequence_counter=sequence_counter,
        payload=payload,
        mic=mic,
    ):
        raise ValueError("MIC verification failed")

    status = payload[0]
    button_names = _extract_active_buttons(status)
    event_type = _extract_event_type(status)

    return ParsedTelegram(
        sequence_counter=sequence_counter,
        buttons=button_names,
        event_type=event_type,
    )


def _extract_active_buttons(status: int) -> tuple[str, ...]:
    return tuple(name for bit, name in BUTTON_BIT_TO_NAME.items() if status & bit)


def _extract_event_type(status: int) -> str:
    # Energy Bar bit encodes push/release action. Long events are derived at runtime.
    return "press" if (status & STATUS_BIT_ENERGY_BOW) else "release"


def parse_commissioning_telegram(telegram: bytes) -> ParsedCommissioningTelegram:
    """Parse commissioning telegram payload from manufacturer data."""
    if len(telegram) != 26:
        raise ValueError("EnOcean commissioning telegram must be exactly 26 bytes")

    sequence_counter = int.from_bytes(telegram[0:4], byteorder="little")
    return ParsedCommissioningTelegram(
        sequence_counter=sequence_counter,
        security_key_hex=telegram[4:20].hex(),
        static_source_address_hex=telegram[20:26].hex(),
    )
