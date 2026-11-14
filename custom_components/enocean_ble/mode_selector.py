"""Button mode selector shared by the config, options and repair flows."""

from __future__ import annotations

from typing import Any

from homeassistant.helpers.selector import (
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)


def button_mode_selector(modes: list[str]) -> Any:
    """Radio list of button modes; labels come from the "button_mode" translations."""
    return SelectSelector(
        SelectSelectorConfig(
            options=list(modes),
            mode=SelectSelectorMode.LIST,
            translation_key="button_mode",
        )
    )
