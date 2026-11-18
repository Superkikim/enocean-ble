"""Repairs for EnOcean BLE: choose a button mode for switches still in Legacy mode."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import voluptuous as vol
from homeassistant.components.repairs import RepairsFlow
from homeassistant.core import HomeAssistant

if TYPE_CHECKING:
    # Type only: not exported by every supported Home Assistant version.
    from homeassistant.components.repairs import RepairsFlowResult

from .const import BUTTON_MODES, CONF_BUTTON_MODE, MODE_LEGACY
from .mode_selector import button_mode_selector
from .usage import find_switch_users


class LegacyButtonModeRepairFlow(RepairsFlow):
    """Let the user pick a new button mode; the switch reloads with it."""

    def __init__(self, entry_id: str) -> None:
        """Initialize the repair flow."""
        self._entry_id = entry_id

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> RepairsFlowResult:
        """Open the repair: Home Assistant passes the issue data here, not an answer."""
        return await self.async_step_confirm()

    async def async_step_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> RepairsFlowResult:
        """Show the modes, with what each Legacy event becomes."""
        entry = self.hass.config_entries.async_get_entry(self._entry_id)
        if entry is None:
            return self.async_abort(reason="entry_not_found")
        if user_input is None:
            return self.async_show_form(
                step_id="confirm",
                # HA 2026.x maps voluptuous onto probatio at runtime; only the type stubs differ.
                data_schema=vol.Schema(  # type: ignore[arg-type,unused-ignore]
                    {
                        vol.Required(CONF_BUTTON_MODE, default=MODE_LEGACY): button_mode_selector(
                            [*BUTTON_MODES, MODE_LEGACY], "button_mode_repair"
                        )
                    }
                ),
                description_placeholders={
                    "name": entry.title,
                    # Computed when the dialog opens, so it is always up to date.
                    "usage": "\n".join(find_switch_users(self.hass, entry)) or "—",
                },
            )
        # The options change reloads the switch in its new mode (update listener).
        self.hass.config_entries.async_update_entry(
            entry, options={**entry.options, CONF_BUTTON_MODE: user_input[CONF_BUTTON_MODE]}
        )
        return self.async_create_entry(data={})


async def async_create_fix_flow(
    hass: HomeAssistant,
    issue_id: str,
    data: dict[str, str | int | float | None] | None,
) -> RepairsFlow:
    """Create the fix flow of a Legacy button mode issue."""
    return LegacyButtonModeRepairFlow(str((data or {}).get("entry_id", "")))
