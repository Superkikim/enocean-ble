"""Validate a module label QR code against a discovered EnOcean BLE switch.

The QR code on the PTM 215B/216B module label contains the switch address and its
AES-128 security key. Before a switch is added from it, three checks run:

1. the text is a valid module label QR code (or free text with MAC + key);
2. its address is the address of the switch that was discovered;
3. its key verifies a telegram really received from that switch (MIC check), or
   matches the key carried by a commissioning telegram.

This module has no Home Assistant dependency so it can be unit tested on its own.
"""

from __future__ import annotations

from collections.abc import Iterable

from .parser import OnboardingData, parse_data_telegram, parse_qr_code

COMMISSIONING_TELEGRAM_LENGTH = 26
DATA_TELEGRAM_MIN_LENGTH = 9

# Error codes, also used as translation keys (config.error.<code>).
ERROR_INVALID_QR = "invalid_qr"
ERROR_MAC_MISMATCH = "qr_mac_mismatch"
ERROR_KEY_INVALID = "qr_key_invalid"
ERROR_NO_TELEGRAM = "qr_no_telegram"


class QrValidationError(ValueError):
    """Raised when a QR code cannot be used for the discovered switch."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def validate_qr_for_device(
    raw: str,
    *,
    mac_address: str,
    payloads: Iterable[bytes],
) -> OnboardingData:
    """Return the onboarding data if ``raw`` belongs to the switch ``mac_address``.

    ``payloads`` are EnOcean manufacturer data payloads recently received from that
    switch (data telegrams and/or commissioning telegrams).
    """
    try:
        onboarding = parse_qr_code(raw)
    except ValueError as err:
        raise QrValidationError(ERROR_INVALID_QR) from err

    if onboarding.mac_address != mac_address.upper():
        raise QrValidationError(ERROR_MAC_MISMATCH)

    seen_any = False
    for payload in payloads:
        if len(payload) == COMMISSIONING_TELEGRAM_LENGTH:
            seen_any = True
            if payload[4:20].hex() == onboarding.security_key_hex:
                return onboarding
            continue
        if len(payload) < DATA_TELEGRAM_MIN_LENGTH:
            continue
        seen_any = True
        try:
            parse_data_telegram(
                payload,
                mac_address=onboarding.mac_address,
                security_key_hex=onboarding.security_key_hex,
            )
        except ValueError:
            continue
        return onboarding

    raise QrValidationError(ERROR_KEY_INVALID if seen_any else ERROR_NO_TELEGRAM)
