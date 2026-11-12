"""Sidebar page to add EnOcean BLE switches by scanning their label QR code."""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import Any

from .const import (
    DOMAIN,
    PANEL_ELEMENT,
    PANEL_FILENAME,
    PANEL_ICON,
    PANEL_STATIC_URL,
    PANEL_TITLE,
    PANEL_URL_PATH,
)

_LOGGER = logging.getLogger(__name__)

FRONTEND_DIR = Path(__file__).parent / "frontend"
DATA_PANEL_REGISTERED = "panel_registered"


def _file_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:12]


async def async_register_panel(hass: Any) -> None:
    """Serve the panel script and register the admin-only sidebar page (once)."""
    if getattr(hass, "http", None) is None:
        return
    domain_data: dict[str, Any] = hass.data.setdefault(DOMAIN, {})
    if domain_data.get(DATA_PANEL_REGISTERED):
        return

    from homeassistant.components import panel_custom
    from homeassistant.components.http import StaticPathConfig

    script = FRONTEND_DIR / PANEL_FILENAME
    digest = await hass.async_add_executor_job(_file_digest, script)

    await hass.http.async_register_static_paths(
        [StaticPathConfig(PANEL_STATIC_URL, str(FRONTEND_DIR), False)]
    )
    await panel_custom.async_register_panel(
        hass,
        webcomponent_name=PANEL_ELEMENT,
        frontend_url_path=PANEL_URL_PATH,
        module_url=f"{PANEL_STATIC_URL}/{PANEL_FILENAME}?v={digest}",
        sidebar_title=PANEL_TITLE,
        sidebar_icon=PANEL_ICON,
        require_admin=True,
        config={},
    )
    domain_data[DATA_PANEL_REGISTERED] = True
    _LOGGER.debug("panel_registered url_path=%s digest=%s", PANEL_URL_PATH, digest)
