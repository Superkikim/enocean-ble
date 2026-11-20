"""Scan the module label QR code with the phone camera, from the config flow.

The config flow opens the scan page as an external step. The page decodes the QR
code in the browser and posts it back here. The QR code is validated against the
discovered switch (address and key) before it is fed to the flow, so errors are
shown on the phone, where the user is scanning, and in Home Assistant, where
the user carries on.

Adapted from hass-pronote (https://github.com/delphiki/hass-pronote, PR #229).
Copyright (c) 2023 delphiki, MIT License.
"""

from __future__ import annotations

import secrets
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from aiohttp import web
from homeassistant.components.bluetooth import async_discovered_service_info
from homeassistant.components.http import StaticPathConfig  # type: ignore[attr-defined]
from homeassistant.data_entry_flow import UnknownFlow
from homeassistant.helpers.http import KEY_HASS, HomeAssistantView
from homeassistant.helpers.network import NoURLAvailableError, get_url

from .const import DOMAIN, ENOCEAN_MANUFACTURER_ID
from .qr_onboarding import QrValidationError, validate_qr_for_device

SCAN_STEP_ID = "qr_scan"
CONF_QR_CODE = "qr_code"
URL_PATH = "/api/enocean_ble/qr_scan/{flow_id}"
STATIC_URL = "/api/enocean_ble/qr_scan_static"

STATIC_DIR = Path(__file__).parent / "qr_scan_static"
DATA_SCAN_SETUP = "qr_scan_setup"


def device_payloads(service_infos: Iterable[Any], mac_address: str) -> list[bytes]:
    """Return the EnOcean payloads currently known for ``mac_address``."""
    payloads: list[bytes] = []
    for info in service_infos:
        if info.address.upper() != mac_address:
            continue
        payload = info.manufacturer_data.get(ENOCEAN_MANUFACTURER_ID)
        if payload is not None:
            payloads.append(bytes(payload))
    return payloads


async def async_setup_scan(hass: Any) -> None:
    """Register the scan page and its static files, once."""
    domain_data: dict[str, Any] = hass.data.setdefault(DOMAIN, {})
    if domain_data.get(DATA_SCAN_SETUP):
        return
    domain_data[DATA_SCAN_SETUP] = True
    page = await hass.async_add_executor_job((STATIC_DIR / "scan.html").read_text, "utf-8")
    await hass.http.async_register_static_paths(
        [StaticPathConfig(STATIC_URL, str(STATIC_DIR), True)]
    )
    hass.http.register_view(QrScanView(page.replace("__STATIC_URL__", STATIC_URL)))


def async_scan_url(hass: Any, flow_id: str) -> str | None:
    """Absolute HTTPS URL of the scan page, None without an HTTPS URL.

    Browsers only give camera access to secure (HTTPS) pages. The URL is unique on
    each call: a browser asked to open a URL it already has open (Safari from the
    phone app) shows that tab again, with the result of the previous scan, instead
    of a new scan page.
    """
    try:
        base = get_url(hass, require_ssl=True, prefer_external=True)
    except NoURLAvailableError:
        return None
    return f"{base}{URL_PATH.format(flow_id=flow_id)}?v={secrets.token_hex(4)}"


def _waiting_flow_mac(hass: Any, flow_id: str) -> str | None:
    """Return the switch address of a flow waiting on the scan step, else None."""
    try:
        flow = hass.config_entries.flow.async_get(flow_id)
    except UnknownFlow:
        return None
    if flow.get("handler") != DOMAIN or flow.get("step_id") != SCAN_STEP_ID:
        return None
    unique_id = (flow.get("context") or {}).get("unique_id")
    return unique_id if isinstance(unique_id, str) else None


class QrScanView(HomeAssistantView):
    """Scan page (GET) and the QR code it reads (POST)."""

    url = URL_PATH
    name = "api:enocean_ble:qr_scan"
    # Opened in a new tab without the HA token, like an OAuth callback: the flow id
    # is the key, and only an EnOcean BLE flow waiting on the scan step is fed.
    # A QR code is only accepted if its key verifies a telegram from that switch.
    requires_auth = False

    def __init__(self, page: str) -> None:
        self._page = page

    async def get(self, request: web.Request, flow_id: str) -> web.Response:
        if _waiting_flow_mac(request.app[KEY_HASS], flow_id) is None:
            return web.Response(status=404)
        return web.Response(
            text=self._page, content_type="text/html", headers={"Cache-Control": "no-store"}
        )

    async def post(self, request: web.Request, flow_id: str) -> web.Response:
        hass = request.app[KEY_HASS]
        mac_address = _waiting_flow_mac(hass, flow_id)
        if mac_address is None:
            return self.json_message("Unknown flow", 404)
        try:
            qr_code = (await request.json())["qr"]
        except (ValueError, KeyError, TypeError):
            qr_code = None
        if not isinstance(qr_code, str):
            return self.json({"code": "invalid_qr"}, 400)

        error: str | None = None
        try:
            validate_qr_for_device(
                qr_code,
                mac_address=mac_address,
                payloads=device_payloads(async_discovered_service_info(hass, connectable=False), mac_address),
            )
        except QrValidationError as err:
            error = err.code

        # Fed either way: the flow checks the QR code again and shows the result
        # (confirmation or error) in Home Assistant, where the user carries on.
        await hass.config_entries.flow.async_configure(
            flow_id=flow_id, user_input={CONF_QR_CODE: qr_code}
        )
        if error is not None:
            return self.json({"code": error}, 400)
        return self.json({"ok": True})
