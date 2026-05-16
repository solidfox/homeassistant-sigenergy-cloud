"""Sigenergy cloud integration for Home Assistant."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.const import CONF_PASSWORD, CONF_USERNAME, Platform
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from sigenergy_cloud import (
    SigenergyCloudAuthError,
    SigenergyCloudClient,
    SigenergyCloudError,
)

from .const import CONF_REGION, DOMAIN
from .coordinator import SigenSettingsCoordinator, SigenStatusCoordinator
from .data import SigenData

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
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


_RENAMED_UNIQUE_ID_SUFFIXES = {
    "dc_charger_latest_session": "dc_charger_last_session",
    "latest_session_record_id": "last_session_record_id",
    "latest_session_started": "last_session_started",
    "latest_session_ended": "last_session_ended",
    "latest_session_duration": "last_session_duration",
    "latest_session_energy_charged": "last_session_energy_charged",
    "latest_session_energy_discharged": "last_session_energy_discharged",
    "latest_session_start_soc": "last_session_start_soc",
    "latest_session_end_soc": "last_session_end_soc",
    "latest_session_end_reason": "last_session_end_reason",
    "latest_session_stop_code": "last_session_stop_code",
    "latest_session_alarm_code": "last_session_alarm_code",
    "latest_session_alarm_name": "last_session_alarm_name",
    "dc_charger_session_started_at": "dc_charger_current_session_started_at",
}

_ENTITY_ID_RENAMES = (
    ("dc_charger_latest_session", "dc_charger_last_session"),
    ("latest_session", "last_session"),
    ("dc_charger_session_started", "dc_charger_current_session_started"),
)


def _migrated_unique_id(unique_id: str) -> str | None:
    for old_suffix, new_suffix in _RENAMED_UNIQUE_ID_SUFFIXES.items():
        marker = f"_{old_suffix}"
        if unique_id.endswith(marker):
            return f"{unique_id.removesuffix(old_suffix)}{new_suffix}"
    return None


def _migrated_entity_id(entity_id: str) -> str | None:
    for old, new in _ENTITY_ID_RENAMES:
        if old in entity_id:
            return entity_id.replace(old, new, 1)
    return None


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate old Sigenergy config entries."""
    if entry.version >= 2:
        return True

    entity_registry = er.async_get(hass)
    for entity in er.async_entries_for_config_entry(entity_registry, entry.entry_id):
        new_unique_id = _migrated_unique_id(entity.unique_id)
        if new_unique_id is None:
            continue

        existing_entity_id = entity_registry.async_get_entity_id(
            entity.domain, DOMAIN, new_unique_id
        )
        if existing_entity_id is not None and existing_entity_id != entity.entity_id:
            continue

        kwargs = {"new_unique_id": new_unique_id}
        new_entity_id = _migrated_entity_id(entity.entity_id)
        if new_entity_id is not None and not entity_registry.async_is_registered(
            new_entity_id
        ):
            kwargs["new_entity_id"] = new_entity_id

        entity_registry.async_update_entity(entity.entity_id, **kwargs)

    hass.config_entries.async_update_entry(entry, version=2)
    return True


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
