"""Sigenergy cloud integration for Home Assistant."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.const import CONF_PASSWORD, CONF_USERNAME, Platform
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from sigenergy_cloud import (
    SigenergyCloudAuthError,
    SigenergyCloudClient,
    SigenergyCloudError,
)

from .const import CONF_REGION
from .coordinator import SigenSettingsCoordinator, SigenStatusCoordinator
from .data import SigenData

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from .data import SigenConfigEntry

PLATFORMS: list[Platform] = [
    Platform.BUTTON,
    Platform.BINARY_SENSOR,
    Platform.SENSOR,
    Platform.NUMBER,
    Platform.SWITCH,
    Platform.SELECT,
]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SigenConfigEntry,
) -> bool:
    """Set up Sigenergy from a config entry."""
    client = SigenergyCloudClient(
        username=entry.data[CONF_USERNAME],
        password=entry.data[CONF_PASSWORD],
        region=entry.data.get(CONF_REGION, "eu"),
        session=async_get_clientsession(hass),
    )

    try:
        await client.connect()
    except SigenergyCloudAuthError as exc:
        raise ConfigEntryAuthFailed(exc) from exc
    except SigenergyCloudError as exc:
        raise ConfigEntryNotReady(exc) from exc

    settings_coordinator = SigenSettingsCoordinator(hass, client)
    status_coordinator = SigenStatusCoordinator(hass, client)

    await settings_coordinator.async_config_entry_first_refresh()
    await status_coordinator.async_config_entry_first_refresh()

    entry.runtime_data = SigenData(
        client=client,
        settings_coordinator=settings_coordinator,
        status_coordinator=status_coordinator,
    )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))

    return True


async def async_unload_entry(
    hass: HomeAssistant,
    entry: SigenConfigEntry,
) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        await entry.runtime_data.client.close()
    return unload_ok


async def async_reload_entry(
    hass: HomeAssistant,
    entry: SigenConfigEntry,
) -> None:
    """Reload a config entry."""
    await hass.config_entries.async_reload(entry.entry_id)
