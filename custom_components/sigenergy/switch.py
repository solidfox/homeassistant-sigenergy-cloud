"""Switch platform for Sigenergy — binary controls with polled state."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.components.switch import SwitchDeviceClass, SwitchEntity

from .entity import SigenSettingsEntity, SigenStatusEntity

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

    from .coordinator import SigenSettingsCoordinator, SigenStatusCoordinator
    from .data import SigenConfigEntry


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SigenConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Sigenergy switch entities."""
    data = entry.runtime_data
    station_id = data.client.station_id

    entities: list[SwitchEntity] = [
        SigenExportLimitSwitch(data.settings_coordinator, station_id),
        SigenImportLimitSwitch(data.settings_coordinator, station_id),
        SigenBatteryExportSwitch(data.settings_coordinator, station_id),
    ]

    if data.client.dc_sn:
        entities.append(
            SigenEVChargeSwitch(data.status_coordinator, station_id, data.client)
        )
        entities.append(
            SigenV2XSwitch(
                data.status_coordinator,
                data.settings_coordinator,
                station_id,
                data.client,
            )
        )

    async_add_entities(entities)


# ── Settings-backed switches ──────────────────────────────────────────────────

class SigenExportLimitSwitch(SigenSettingsEntity, SwitchEntity):
    """Enable/disable the grid export power limit."""

    _attr_translation_key = "export_limit_enabled"
    _attr_device_class = SwitchDeviceClass.SWITCH
    _attr_icon = "mdi:transmission-tower-export"

    def __init__(self, coordinator: SigenSettingsCoordinator, station_id: str) -> None:
        super().__init__(coordinator, station_id, "export_limit_enabled")

    @property
    def is_on(self) -> bool | None:
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.get("export_limit", {}).get("enable")

    async def async_turn_on(self, **kwargs: Any) -> None:
        current = self.coordinator.data.get("export_limit", {})
        limit_kw = float(current.get("maxLimitationOwner") or 0)
        await self.coordinator.client.set_export_limit(limit_kw, enabled=True)
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        current = self.coordinator.data.get("export_limit", {})
        limit_kw = float(current.get("maxLimitationOwner") or 0)
        await self.coordinator.client.set_export_limit(limit_kw, enabled=False)
        await self.coordinator.async_request_refresh()


class SigenImportLimitSwitch(SigenSettingsEntity, SwitchEntity):
    """Enable/disable the grid import power limit."""

    _attr_translation_key = "import_limit_enabled"
    _attr_device_class = SwitchDeviceClass.SWITCH
    _attr_icon = "mdi:transmission-tower-import"

    def __init__(self, coordinator: SigenSettingsCoordinator, station_id: str) -> None:
        super().__init__(coordinator, station_id, "import_limit_enabled")

    @property
    def is_on(self) -> bool | None:
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.get("import_limit", {}).get("enable")

    async def async_turn_on(self, **kwargs: Any) -> None:
        current = self.coordinator.data.get("import_limit", {})
        limit_kw = float(current.get("maxLimitationOwner") or 0)
        await self.coordinator.client.set_import_limit(limit_kw, enabled=True)
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        current = self.coordinator.data.get("import_limit", {})
        limit_kw = float(current.get("maxLimitationOwner") or 0)
        await self.coordinator.client.set_import_limit(limit_kw, enabled=False)
        await self.coordinator.async_request_refresh()


class SigenBatteryExportSwitch(SigenSettingsEntity, SwitchEntity):
    """Allow or block battery-to-grid export."""

    _attr_translation_key = "battery_export_enabled"
    _attr_device_class = SwitchDeviceClass.SWITCH
    _attr_icon = "mdi:battery-arrow-right"

    def __init__(self, coordinator: SigenSettingsCoordinator, station_id: str) -> None:
        super().__init__(coordinator, station_id, "battery_export_enabled")

    @property
    def is_on(self) -> bool | None:
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.get("battery_export", {}).get("ownerSetEnable")

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.client.set_battery_export_limitation(True)
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.client.set_battery_export_limitation(False)
        await self.coordinator.async_request_refresh()


# ── Status-backed switches (polled every 30 s) ────────────────────────────────

class SigenEVChargeSwitch(SigenStatusEntity, SwitchEntity):
    """Start/stop EV charging with live charging state."""

    _attr_translation_key = "ev_charge_enabled"
    _attr_device_class = SwitchDeviceClass.SWITCH
    _attr_icon = "mdi:ev-plug-type2"

    def __init__(
        self,
        coordinator: SigenStatusCoordinator,
        station_id: str,
        client: Any,
    ) -> None:
        super().__init__(coordinator, station_id, "ev_charge_enabled")
        self._client = client

    @property
    def is_on(self) -> bool | None:
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.get("is_charging")

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._client.set_charge_enabled(True)
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._client.set_charge_enabled(False)
        await self.coordinator.async_request_refresh()


class SigenV2XSwitch(SigenStatusEntity, SwitchEntity):
    """Start/stop a V2X discharge session with live active state.

    Turn on starts a discharge using the current V2X Power Cap setting.
    Turn off stops any running session. State is polled every 30 s.
    """

    _attr_translation_key = "v2x_discharge"
    _attr_device_class = SwitchDeviceClass.SWITCH
    _attr_icon = "mdi:car-battery"

    def __init__(
        self,
        status_coordinator: SigenStatusCoordinator,
        settings_coordinator: SigenSettingsCoordinator,
        station_id: str,
        client: Any,
    ) -> None:
        super().__init__(status_coordinator, station_id, "v2x_discharge")
        self._settings = settings_coordinator
        self._client = client

    @property
    def is_on(self) -> bool | None:
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.get("v2x_active")

    async def async_turn_on(self, **kwargs: Any) -> None:
        cap = self._settings.v2x_power_cap_kw  # None = no cap
        await self._client.start_v2x_discharge(duration_minutes=120, power_cap_kw=cap)
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._client.stop_v2x_discharge()
        await self.coordinator.async_request_refresh()
