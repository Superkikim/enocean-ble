"""Tests for AES-128 MIC helpers."""

from __future__ import annotations

from custom_components.enocean_ble.crypto import calculate_mic, verify_mic


def test_calculate_and_verify_mic() -> None:
    key = bytes.fromhex("00112233445566778899AABBCCDDEEFF")
    mac = bytes.fromhex("DDCCBBAA15E2")
    seq = 123456
    payload = bytes([0x03])

    mic = calculate_mic(key, mac, seq, payload)

    assert len(mic) == 4
    assert verify_mic(key, mac, seq, payload, mic)


def test_verify_mic_rejects_tampered_payload() -> None:
    key = bytes.fromhex("00112233445566778899AABBCCDDEEFF")
    mac = bytes.fromhex("DDCCBBAA15E2")
    seq = 9
    payload = bytes([0x23])

    mic = calculate_mic(key, mac, seq, payload)

    assert not verify_mic(key, mac, seq, bytes([0x03]), mic)


def test_verify_mic_matches_official_ptm215b_vector() -> None:
    # PTM 215B User Manual v2.2, Appendix C.3.1
    key = bytes.fromhex("3DDA31AD44767AE3CE56DCE2B3CE2ABB")
    source_little = bytes.fromhex("B819000015E2")
    seq = int.from_bytes(bytes.fromhex("5D040000"), byteorder="little")
    payload = bytes.fromhex("11")
    expected_mic = bytes.fromhex("B2FA88FF")

    mic = calculate_mic(key, source_little, seq, payload)
    assert mic == expected_mic
