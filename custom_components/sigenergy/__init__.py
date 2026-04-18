"""Sigenergy cloud integration for Home Assistant."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.const import CONF_PASSWORD, CONF_USERNAME, Platform
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady

from .const import CONF_REGION, DOMAIN, LOGGER
from .coordinator import SigenSettingsCoordinator
from .data import SigenData
from .sigen import Sigen
from .sigen.exceptions import SigenAuthError, SigenError

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from .data import SigenConfigEntry

PLATFORMS: list[Platform] = [
    Platform.NUMBER,
    Platform.SWITCH,
    Platform.SELECT,
    Platform.BUTTON,
]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SigenConfigEntry,
) -> bool:
    """Set up Sigenergy from a config entry."""
    client = Sigen(
        username=entry.data[CONF_USERNAME],
        password=entry.data[CONF_PASSWORD],
        region=entry.data.get(CONF_REGION, "eu"),
    )

    try:
        await client.async_initialize()
    except SigenAuthError as exc:
        raise ConfigEntryAuthFailed(exc) from exc
    except SigenError as exc:
        raise ConfigEntryNotReady(exc) from exc

    settings_coordinator = SigenSettingsCoordinator(hass, client)
    await settings_coordinator.async_config_entry_first_refresh()

    entry.runtime_data = SigenData(
        client=client,
        settings_coordinator=settings_coordinator,
    )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))

    return True


async def async_unload_entry(
    hass: HomeAssistant,
    entry: SigenConfigEntry,
) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_reload_entry(
    hass: HomeAssistant,
    entry: SigenConfigEntry,
) -> None:
    """Reload a config entry."""
    await hass.config_entries.async_reload(entry.entry_id)
