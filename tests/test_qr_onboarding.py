"""Tests for validating a module label QR code against a discovered switch."""

from __future__ import annotations

import pytest

from custom_components.enocean_ble.qr_onboarding import (
    ERROR_INVALID_QR,
    ERROR_KEY_INVALID,
    ERROR_MAC_MISMATCH,
    ERROR_NO_TELEGRAM,
    QrValidationError,
    validate_qr_for_device,
)

# PTM 215B User Manual v2.2, Appendix C.3.1: address, key and a real data telegram.
MAC = "E2:15:00:00:19:B8"
KEY = "3dda31ad44767ae3ce56dce2b3ce2abb"
QR = "30SE215000019B8+Z3DDA31AD44767AE3CE56DCE2B3CE2ABB+30PS3221-A215+2PDD07+S01546701167343"
DATA_TELEGRAM = bytes.fromhex("5D04000011B2FA88FF")
OTHER_KEY_QR = "30SE215000019B8+Z00112233445566778899AABBCCDDEEFF+30PS3221-A215"


def _commissioning_telegram(key_hex: str) -> bytes:
    # sequence counter (4) + security key (16) + static source address (6)
    return bytes.fromhex("01000000") + bytes.fromhex(key_hex) + bytes.fromhex("B819000015E2")


def _error_code(raw: str, *, mac: str = MAC, payloads: list[bytes]) -> str:
    with pytest.raises(QrValidationError) as err:
        validate_qr_for_device(raw, mac_address=mac, payloads=payloads)
    return err.value.code


def test_valid_qr_verified_by_data_telegram() -> None:
    result = validate_qr_for_device(QR, mac_address=MAC, payloads=[DATA_TELEGRAM])
    assert result.mac_address == MAC
    assert result.security_key_hex == KEY


def test_mac_comparison_is_case_insensitive() -> None:
    result = validate_qr_for_device(QR, mac_address=MAC.lower(), payloads=[DATA_TELEGRAM])
    assert result.mac_address == MAC


def test_valid_qr_verified_by_commissioning_telegram() -> None:
    result = validate_qr_for_device(QR, mac_address=MAC, payloads=[_commissioning_telegram(KEY)])
    assert result.security_key_hex == KEY


def test_one_matching_telegram_among_others_is_enough() -> None:
    other = bytes.fromhex("5E04000011AABBCCDD")  # MIC does not verify
    result = validate_qr_for_device(QR, mac_address=MAC, payloads=[other, DATA_TELEGRAM])
    assert result.mac_address == MAC


@pytest.mark.parametrize(
    "raw",
    ["", "hello", "30SE215000019B8+30PS3221-A215", "https://example.com/not-an-enocean-code"],
)
def test_invalid_format(raw: str) -> None:
    assert _error_code(raw, payloads=[DATA_TELEGRAM]) == ERROR_INVALID_QR


def test_qr_of_another_switch() -> None:
    assert _error_code(QR, mac="E2:15:00:03:C6:ED", payloads=[DATA_TELEGRAM]) == ERROR_MAC_MISMATCH


def test_wrong_key_rejected_by_mic() -> None:
    assert _error_code(OTHER_KEY_QR, payloads=[DATA_TELEGRAM]) == ERROR_KEY_INVALID


def test_wrong_key_rejected_by_commissioning_telegram() -> None:
    assert _error_code(QR, payloads=[_commissioning_telegram("00" * 16)]) == ERROR_KEY_INVALID


def test_no_telegram_received() -> None:
    assert _error_code(QR, payloads=[]) == ERROR_NO_TELEGRAM


def test_too_short_payloads_are_ignored() -> None:
    assert _error_code(QR, payloads=[b"\x01\x02\x03"]) == ERROR_NO_TELEGRAM
