"""Tests for the QR scan sidebar panel registration."""

from __future__ import annotations

from types import SimpleNamespace

from custom_components.enocean_ble.const import DOMAIN, PANEL_FILENAME
from custom_components.enocean_ble.panel import FRONTEND_DIR, async_register_panel


def test_panel_script_is_packaged() -> None:
    assert (FRONTEND_DIR / PANEL_FILENAME).is_file()


async def test_register_panel_skips_without_http() -> None:
    hass = SimpleNamespace(data={})
    await async_register_panel(hass)
    assert hass.data == {}


async def test_register_panel_runs_once() -> None:
    hass = SimpleNamespace(http=object(), data={DOMAIN: {"panel_registered": True}})
    # Already registered: must return before touching hass.http.
    await async_register_panel(hass)
    assert hass.data[DOMAIN] == {"panel_registered": True}
