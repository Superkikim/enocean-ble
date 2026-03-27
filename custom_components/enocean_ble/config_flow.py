"""Config flow for EnOcean BLE integration."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.components.bluetooth import async_discovered_service_info
from homeassistant.data_entry_flow import FlowResult

from .const import (
    CONF_MAC_ADDRESS,
    CONF_NFC_RAW,
    CONF_QR_RAW,
    CONF_SECURITY_KEY,
    CONF_SETUP_METHOD,
    DOMAIN,
    ENOCEAN_MANUFACTURER_ID,
    SETUP_METHOD_NFC,
    SETUP_METHOD_QR,
)
from .parser import parse_onboarding_blob


class EnOceanBleConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):  # type: ignore[misc,call-arg]
    """Handle a config flow for EnOcean BLE."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Choose onboarding method."""
        if user_input is not None:
            method = user_input[CONF_SETUP_METHOD]
            if method == SETUP_METHOD_QR:
                return await self.async_step_qr()
            if method == SETUP_METHOD_NFC:
                return await self.async_step_nfc()

        schema = vol.Schema(
            {
                vol.Required(CONF_SETUP_METHOD, default=SETUP_METHOD_QR): vol.In(
                    [SETUP_METHOD_QR, SETUP_METHOD_NFC]
                )
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema)

    async def async_step_qr(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Handle raw QR onboarding payload."""
        return await self._async_step_raw_payload(
            step_id="qr",
            field_name=CONF_QR_RAW,
            setup_method=SETUP_METHOD_QR,
            invalid_error="invalid_qr_data",
            not_detected_error="device_not_detected",
            user_input=user_input,
        )

    async def async_step_nfc(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Handle raw NFC onboarding payload."""
        return await self._async_step_raw_payload(
            step_id="nfc",
            field_name=CONF_NFC_RAW,
            setup_method=SETUP_METHOD_NFC,
            invalid_error="invalid_nfc_data",
            not_detected_error="device_not_detected",
            user_input=user_input,
        )

    async def _async_step_raw_payload(
        self,
        *,
        step_id: str,
        field_name: str,
        setup_method: str,
        invalid_error: str,
        not_detected_error: str,
        user_input: dict[str, Any] | None,
    ) -> FlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                parsed = parse_onboarding_blob(user_input[field_name])
            except ValueError:
                errors["base"] = invalid_error
            else:
                if not await self._async_is_device_discoverable(parsed.mac_address):
                    errors["base"] = not_detected_error
                else:
                    await self.async_set_unique_id(parsed.mac_address)
                    self._abort_if_unique_id_configured()
                    return self.async_create_entry(
                        title=f"EnOcean BLE {parsed.mac_address}",
                        data={
                            CONF_SETUP_METHOD: setup_method,
                            CONF_MAC_ADDRESS: parsed.mac_address,
                            CONF_SECURITY_KEY: parsed.security_key_hex,
                        },
                    )

        schema = vol.Schema({vol.Required(field_name): str})
        return self.async_show_form(step_id=step_id, data_schema=schema, errors=errors)

    async def _async_is_device_discoverable(self, mac_address: str) -> bool:
        """Validate that device can be seen in active BLE discoveries."""
        for discovery_info in async_discovered_service_info(self.hass):
            if discovery_info.address.upper() != mac_address.upper():
                continue
            if ENOCEAN_MANUFACTURER_ID in discovery_info.manufacturer_data:
                return True
        return False
