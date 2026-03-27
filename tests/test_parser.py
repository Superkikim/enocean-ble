"""Tests for onboarding and telegram parser helpers."""

from __future__ import annotations

import pytest

from custom_components.enocean_ble.crypto import calculate_mic
from custom_components.enocean_ble.parser import (
    parse_commissioning_telegram,
    parse_data_telegram,
    parse_onboarding_blob,
)


def test_parse_onboarding_blob_ok() -> None:
    raw = "MAC=E2:15:AA:BB:CC:DD KEY=00112233445566778899AABBCCDDEEFF"
    parsed = parse_onboarding_blob(raw)
    assert parsed.mac_address == "E2:15:AA:BB:CC:DD"
    assert parsed.security_key_hex == "00112233445566778899aabbccddeeff"


@pytest.mark.parametrize(
    "raw",
    [
        "MAC=11:22:33:44:55:66 KEY=00112233445566778899AABBCCDDEEFF",
        "MAC=E2:15:AA:BB:CC:DD",
        "KEY=00112233445566778899AABBCCDDEEFF",
    ],
)
def test_parse_onboarding_blob_invalid(raw: str) -> None:
    with pytest.raises(ValueError):
        parse_onboarding_blob(raw)


def test_parse_data_telegram_ok_press() -> None:
    key_hex = "00112233445566778899aabbccddeeff"
    mac = "E2:15:AA:BB:CC:DD"
    seq = 42
    status = 0x01 | 0x04  # pressed + A1

    payload = bytes([status])
    mic = calculate_mic(bytes.fromhex(key_hex), bytes.fromhex("DDCCBBAA15E2"), seq, payload)
    telegram = seq.to_bytes(4, byteorder="little") + payload + mic

    parsed = parse_data_telegram(telegram, mac_address=mac, security_key_hex=key_hex)

    assert parsed.sequence_counter == 42
    assert parsed.button == "A1"
    assert parsed.event_type == "press"


def test_parse_data_telegram_rejects_bad_mic() -> None:
    key_hex = "00112233445566778899aabbccddeeff"
    mac = "E2:15:AA:BB:CC:DD"
    seq = 1
    payload = bytes([0x03])
    telegram = seq.to_bytes(4, byteorder="little") + payload + b"\x00\x00\x00\x00"

    with pytest.raises(ValueError, match="MIC verification failed"):
        parse_data_telegram(telegram, mac_address=mac, security_key_hex=key_hex)


def test_parse_data_telegram_rejects_multiple_buttons() -> None:
    key_hex = "00112233445566778899aabbccddeeff"
    mac = "E2:15:AA:BB:CC:DD"
    seq = 3
    payload = bytes([0x01 | 0x02 | 0x04])  # pressed + A0 + A1
    mic = calculate_mic(bytes.fromhex(key_hex), bytes.fromhex("DDCCBBAA15E2"), seq, payload)
    telegram = seq.to_bytes(4, byteorder="little") + payload + mic

    with pytest.raises(ValueError, match="exactly one active button"):
        parse_data_telegram(telegram, mac_address=mac, security_key_hex=key_hex)


def test_parse_data_telegram_manual_vector() -> None:
    # PTM 215B User Manual v2.2, Appendix C.3.1
    key_hex = "3DDA31AD44767AE3CE56DCE2B3CE2ABB".lower()
    mac = "E2:15:00:00:19:B8"
    telegram = bytes.fromhex("5D04000011B2FA88FF")

    parsed = parse_data_telegram(telegram, mac_address=mac, security_key_hex=key_hex)
    assert parsed.sequence_counter == int.from_bytes(bytes.fromhex("5D040000"), "little")
    assert parsed.button == "B1"
    assert parsed.event_type == "press"


def test_parse_commissioning_telegram_ok() -> None:
    telegram = bytes.fromhex(
        "71010000" "AB4B9A91852B70B8A652A05E92BB12A0" "9F1B000015E2"
    )
    parsed = parse_commissioning_telegram(telegram)

    assert parsed.sequence_counter == 0x00000171
    assert parsed.security_key_hex == "ab4b9a91852b70b8a652a05e92bb12a0"
    assert parsed.static_source_address_hex == "9f1b000015e2"
