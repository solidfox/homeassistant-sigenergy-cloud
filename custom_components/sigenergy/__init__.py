"""Sigenergy cloud integration for Home Assistant."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from homeassistant.const import CONF_PASSWORD, CONF_USERNAME, Platform
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady, HomeAssistantError
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from sigenergy_cloud import (
    InstantManualControl,
    InstantManualMode,
    SigenergyCloudAuthError,
    SigenergyCloudClient,
    SigenergyCloudError,
)
import voluptuous as vol

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

SERVICE_SET_INSTANT_MANUAL_CONTROL = "set_instant_manual_control"
SERVICE_DISABLE_INSTANT_MANUAL_CONTROL = "disable_instant_manual_control"

_INSTANT_MANUAL_MODE_ALIASES = {
    "0": InstantManualMode.CHARGING,
    "charging": InstantManualMode.CHARGING,
    "charge": InstantManualMode.CHARGING,
    "1": InstantManualMode.DISCHARGING,
    "discharging": InstantManualMode.DISCHARGING,
    "discharge": InstantManualMode.DISCHARGING,
    "2": InstantManualMode.HOLD_BATTERY,
    "hold_battery": InstantManualMode.HOLD_BATTERY,
    "hold battery": InstantManualMode.HOLD_BATTERY,
    "hold": InstantManualMode.HOLD_BATTERY,
    "3": InstantManualMode.SELF_CONSUMPTION,
    "self_consumption": InstantManualMode.SELF_CONSUMPTION,
    "self-consumption": InstantManualMode.SELF_CONSUMPTION,
    "self consumption": InstantManualMode.SELF_CONSUMPTION,
}

_SET_INSTANT_MANUAL_SCHEMA = vol.Schema(
    {
        vol.Required("mode"): vol.All(str, vol.Lower, vol.In(_INSTANT_MANUAL_MODE_ALIASES)),
        vol.Optional("duration_minutes", default=30): vol.All(
            vol.Coerce(int), vol.Range(min=30, max=120)
        ),
        vol.Optional("power_limitation_kw"): vol.All(
            vol.Coerce(float), vol.Range(min=0.0)
        ),
        vol.Optional("entry_id"): cv.string,
    }
)

_DISABLE_INSTANT_MANUAL_SCHEMA = vol.Schema(
    {
        vol.Optional("entry_id"): cv.string,
    }
)


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
    if entry.version >= 3:
        return True

    if entry.unique_id is not None and not isinstance(entry.unique_id, str):
        hass.config_entries.async_update_entry(entry, unique_id=str(entry.unique_id))

    if entry.version >= 2:
        hass.config_entries.async_update_entry(entry, version=3)
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

    hass.config_entries.async_update_entry(entry, version=3)
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

    _async_register_services(hass)

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


def _async_register_services(hass: HomeAssistant) -> None:
    """Register station-level Sigenergy services once."""
    if hass.services.has_service(DOMAIN, SERVICE_SET_INSTANT_MANUAL_CONTROL):
        return

    async def async_set_instant_manual_control(call) -> None:
        entry = _service_config_entry(hass, call.data.get("entry_id"))
        data = entry.runtime_data
        mode = _INSTANT_MANUAL_MODE_ALIASES[call.data["mode"]]
        duration_minutes = call.data["duration_minutes"]
        await data.client.set_instant_manual_control(
            mode,
            duration_minutes=duration_minutes,
            power_limitation_kw=call.data.get("power_limitation_kw"),
        )
        data.settings_coordinator.async_update_local_data(
            {
                "instant_manual": InstantManualControl(
                    enabled=True,
                    mode=mode,
                    end_time=int(time.time()) + duration_minutes * 60,
                )
            }
        )

    async def async_disable_instant_manual_control(call) -> None:
        entry = _service_config_entry(hass, call.data.get("entry_id"))
        data = entry.runtime_data
        await data.client.disable_instant_manual_control()
        data.settings_coordinator.async_update_local_data(
            {
                "instant_manual": InstantManualControl(
                    enabled=False,
                    mode=None,
                    end_time=None,
                )
            }
        )

    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_INSTANT_MANUAL_CONTROL,
        async_set_instant_manual_control,
        schema=_SET_INSTANT_MANUAL_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_DISABLE_INSTANT_MANUAL_CONTROL,
        async_disable_instant_manual_control,
        schema=_DISABLE_INSTANT_MANUAL_SCHEMA,
    )


def _service_config_entry(hass: HomeAssistant, entry_id: str | None) -> SigenConfigEntry:
    """Return the target config entry for a station-level service call."""
    if entry_id:
        entry = hass.config_entries.async_get_entry(entry_id)
        if entry is None or entry.domain != DOMAIN:
            raise HomeAssistantError(f"Unknown Sigenergy config entry: {entry_id}")
        return entry

    loaded_entries = [
        entry
        for entry in hass.config_entries.async_entries(DOMAIN)
        if getattr(entry, "runtime_data", None) is not None
    ]
    if len(loaded_entries) != 1:
        raise HomeAssistantError("Specify entry_id when multiple Sigenergy entries are loaded")
    return loaded_entries[0]
