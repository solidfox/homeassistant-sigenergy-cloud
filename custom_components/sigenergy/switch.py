"""Switch platform for Sigenergy — binary on/off controls."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.components.switch import SwitchDeviceClass, SwitchEntity

from .entity import SigenSettingsEntity

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

    from .coordinator import SigenSettingsCoordinator
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
        entities.append(SigenEVChargeSwitch(data.settings_coordinator, station_id, data.client))

    async_add_entities(entities)


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
        limit_kw = float(current.get("maxLimitationOwner", 0) or 0)
        await self.coordinator.client.set_export_limit(limit_kw, enabled=True)
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        current = self.coordinator.data.get("export_limit", {})
        limit_kw = float(current.get("maxLimitationOwner", 0) or 0)
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
        limit_kw = float(current.get("maxLimitationOwner", 0) or 0)
        await self.coordinator.client.set_import_limit(limit_kw, enabled=True)
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        current = self.coordinator.data.get("import_limit", {})
        limit_kw = float(current.get("maxLimitationOwner", 0) or 0)
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
        battery_export = self.coordinator.data.get("battery_export", {})
        return battery_export.get("ownerSetEnable")

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.client.set_battery_export_limitation(True)
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.client.set_battery_export_limitation(False)
        await self.coordinator.async_request_refresh()


class SigenEVChargeSwitch(SigenSettingsEntity, SwitchEntity):
    """Start or stop EV charging on the DC charger.

    State is not tracked here — use the local Modbus dc_charger_running_state
    sensor for actual charging status. This entity is write-only.
    """

    _attr_translation_key = "ev_charge_enabled"
    _attr_device_class = SwitchDeviceClass.SWITCH
    _attr_icon = "mdi:ev-plug-type2"

    def __init__(
        self,
        coordinator: SigenSettingsCoordinator,
        station_id: str,
        client: Any,
    ) -> None:
        super().__init__(coordinator, station_id, "ev_charge_enabled")
        self._client = client

    @property
    def is_on(self) -> bool | None:
        return None  # State read from Modbus dc_charger_running_state

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._client.set_charge_enabled(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._client.set_charge_enabled(False)
