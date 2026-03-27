"""Cryptographic helpers for EnOcean BLE MIC handling."""

from __future__ import annotations

from cryptography.hazmat.primitives.ciphers.aead import AESCCM

from .const import ENOCEAN_MANUFACTURER_ID, MIC_LENGTH


def build_nonce(mac_address_bytes: bytes, sequence_counter: int) -> bytes:
    """Build 13-byte nonce for EnOcean BLE MIC computation.

    The address must be supplied in little-endian source-address order.
    """
    if len(mac_address_bytes) != 6:
        raise ValueError("MAC address bytes must be 6 bytes long")
    if not (0 <= sequence_counter <= 0xFFFFFFFF):
        raise ValueError("Sequence counter must be in 32-bit range")

    return mac_address_bytes + sequence_counter.to_bytes(4, byteorder="little") + b"\x00\x00\x00"


def build_aad(sequence_counter: int, payload: bytes) -> bytes:
    """Build authenticated associated data for data telegram verification."""
    if not (0 <= sequence_counter <= 0xFFFFFFFF):
        raise ValueError("Sequence counter must be in 32-bit range")

    # Type(1) + Manufacturer(2) + Sequence(4) + Payload(N) + MIC(4)
    frame_length = 1 + 2 + 4 + len(payload) + MIC_LENGTH
    type_byte = b"\xFF"
    manufacturer_le = ENOCEAN_MANUFACTURER_ID.to_bytes(2, byteorder="little")

    return (
        frame_length.to_bytes(1, byteorder="big")
        + type_byte
        + manufacturer_le
        + sequence_counter.to_bytes(4, byteorder="little")
        + payload
    )


def calculate_mic(
    security_key: bytes,
    mac_address_bytes: bytes,
    sequence_counter: int,
    payload: bytes,
) -> bytes:
    """Calculate 4-byte MIC tag for EnOcean BLE telegram payload."""
    if len(security_key) != 16:
        raise ValueError("Security key must be 16 bytes (AES-128)")

    nonce = build_nonce(mac_address_bytes, sequence_counter)
    aad = build_aad(sequence_counter, payload)

    aesccm = AESCCM(security_key, tag_length=MIC_LENGTH)
    return aesccm.encrypt(nonce=nonce, data=b"", associated_data=aad)


def verify_mic(
    security_key: bytes,
    mac_address_bytes: bytes,
    sequence_counter: int,
    payload: bytes,
    mic: bytes,
) -> bool:
    """Verify 4-byte MIC for a telegram payload."""
    if len(mic) != MIC_LENGTH:
        return False

    try:
        expected = calculate_mic(
            security_key=security_key,
            mac_address_bytes=mac_address_bytes,
            sequence_counter=sequence_counter,
            payload=payload,
        )
    except ValueError:
        return False

    return expected == mic
