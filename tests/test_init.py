"""Basic setup tests for integration bootstrap."""

from __future__ import annotations

from types import SimpleNamespace

from custom_components.enocean_ble import async_setup
from custom_components.enocean_ble.const import DOMAIN


async def test_async_setup_initializes_domain() -> None:
    hass = SimpleNamespace(data={})
    assert await async_setup(hass, {}) is True
    assert DOMAIN in hass.data
