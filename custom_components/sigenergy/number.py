"""Number platform for Sigenergy — configurable setpoints."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from homeassistant.components.number import (
    NumberDeviceClass,
    NumberEntity,
    NumberEntityDescription,
    NumberMode,
)
from homeassistant.const import PERCENTAGE, UnitOfPower

from .entity import SigenSettingsEntity
from .sigen.battery_level import BatteryLevelSettings

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

    from .coordinator import SigenSettingsCoordinator
    from .data import SigenConfigEntry


@dataclass(frozen=True, kw_only=True)
class SigenNumberDescription(NumberEntityDescription):
    """Number description with write-back helper."""

    # Which top-level key in coordinator.data holds this value
    data_key: str
    # How to extract the float value from coordinator.data[data_key]
    # Provided as a lambda string in the description; resolved in the entity.
    # Alternatively we use a subclass per type.


# ── Descriptions ─────────────────────────────────────────────────────────────

POWER_LIMIT_NUMBERS: tuple[SigenNumberDescription, ...] = (
    SigenNumberDescription(
        key="export_limit_kw",
        data_key="export_limit",
        translation_key="export_limit",
        device_class=NumberDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        native_min_value=0.0,
        native_max_value=100.0,
        native_step=0.5,
        mode=NumberMode.BOX,
        icon="mdi:transmission-tower-export",
    ),
    SigenNumberDescription(
        key="import_limit_kw",
        data_key="import_limit",
        translation_key="import_limit",
        device_class=NumberDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        native_min_value=0.0,
        native_max_value=100.0,
        native_step=0.5,
        mode=NumberMode.BOX,
        icon="mdi:transmission-tower-import",
    ),
)

BATTERY_NUMBERS: tuple[SigenNumberDescription, ...] = (
    SigenNumberDescription(
        key="battery_charge_soc",
        data_key="battery_level",
        translation_key="battery_charge_soc",
        native_unit_of_measurement=PERCENTAGE,
        native_min_value=1.0,
        native_max_value=100.0,
        native_step=1.0,
        mode=NumberMode.BOX,
        icon="mdi:battery-arrow-up",
    ),
    SigenNumberDescription(
        key="battery_discharge_soc",
        data_key="battery_level",
        translation_key="battery_discharge_soc",
        native_unit_of_measurement=PERCENTAGE,
        native_min_value=0.0,
        native_max_value=99.0,
        native_step=1.0,
        mode=NumberMode.BOX,
        icon="mdi:battery-arrow-down",
    ),
    SigenNumberDescription(
        key="battery_peak_shaving_soc",
        data_key="battery_level",
        translation_key="battery_peak_shaving_soc",
        native_unit_of_measurement=PERCENTAGE,
        native_min_value=0.0,
        native_max_value=100.0,
        native_step=1.0,
        mode=NumberMode.BOX,
        icon="mdi:battery-clock",
    ),
    SigenNumberDescription(
        key="battery_backup_soc",
        data_key="battery_level",
        translation_key="battery_backup_soc",
        native_unit_of_measurement=PERCENTAGE,
        native_min_value=0.0,
        native_max_value=100.0,
        native_step=1.0,
        mode=NumberMode.BOX,
        icon="mdi:battery-heart",
    ),
)

BACKUP_RESERVE_NUMBER = SigenNumberDescription(
    key="backup_reserve",
    data_key="backup_reserve",
    translation_key="backup_reserve",
    native_unit_of_measurement=PERCENTAGE,
    native_min_value=0.0,
    native_max_value=100.0,
    native_step=1.0,
    mode=NumberMode.BOX,
    icon="mdi:shield-battery",
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SigenConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Sigenergy number entities."""
    data = entry.runtime_data
    coordinator = data.settings_coordinator
    station_id = data.client.station_id

    entities: list[SigenNumber] = []
    for desc in POWER_LIMIT_NUMBERS:
        entities.append(SigenPowerLimitNumber(coordinator, station_id, desc))
    for desc in BATTERY_NUMBERS:
        entities.append(SigenBatterySOCNumber(coordinator, station_id, desc))
    entities.append(SigenBackupReserveNumber(coordinator, station_id, BACKUP_RESERVE_NUMBER))

    async_add_entities(entities)


class SigenNumber(SigenSettingsEntity, NumberEntity):
    """Base class for Sigenergy number entities."""

    entity_description: SigenNumberDescription

    def __init__(
        self,
        coordinator: SigenSettingsCoordinator,
        station_id: str,
        description: SigenNumberDescription,
    ) -> None:
        super().__init__(coordinator, station_id, description.key)
        self.entity_description = description


class SigenPowerLimitNumber(SigenNumber):
    """Grid export or import power limit (kW)."""

    @property
    def native_value(self) -> float | None:
        if self.coordinator.data is None:
            return None
        limit_data = self.coordinator.data.get(self.entity_description.data_key)
        if limit_data is None:
            return None
        raw = limit_data.get("maxLimitationOwner")
        return float(raw) if raw is not None else None

    async def async_set_native_value(self, value: float) -> None:
        current = self.coordinator.data.get(self.entity_description.data_key) or {}
        enabled = current.get("enable", True)
        if self.entity_description.key == "export_limit_kw":
            await self.coordinator.client.set_export_limit(value, enabled=enabled)
        else:
            await self.coordinator.client.set_import_limit(value, enabled=enabled)
        await self.coordinator.async_request_refresh()


class SigenBatterySOCNumber(SigenNumber):
    """One of the four battery SOC limit fields."""

    # Maps entity key → BatteryLevelSettings attribute name
    _SOC_FIELD: dict[str, str] = {
        "battery_charge_soc": "charge_soc",
        "battery_discharge_soc": "discharge_soc",
        "battery_peak_shaving_soc": "peak_shaving_soc",
        "battery_backup_soc": "backup_soc",
    }

    @property
    def native_value(self) -> float | None:
        if self.coordinator.data is None:
            return None
        settings: BatteryLevelSettings | None = self.coordinator.data.get("battery_level")
        if settings is None:
            return None
        field = self._SOC_FIELD[self.entity_description.key]
        return float(getattr(settings, field))

    async def async_set_native_value(self, value: float) -> None:
        current: BatteryLevelSettings = self.coordinator.data["battery_level"]
        field = self._SOC_FIELD[self.entity_description.key]
        new_settings = BatteryLevelSettings(
            charge_soc=int(value) if field == "charge_soc" else current.charge_soc,
            discharge_soc=int(value) if field == "discharge_soc" else current.discharge_soc,
            peak_shaving_soc=int(value) if field == "peak_shaving_soc" else current.peak_shaving_soc,
            backup_soc=int(value) if field == "backup_soc" else current.backup_soc,
        )
        await self.coordinator.client.set_battery_level_settings(new_settings)
        await self.coordinator.async_request_refresh()


class SigenBackupReserveNumber(SigenNumber):
    """Backup reserve SOC percentage."""

    @property
    def native_value(self) -> float | None:
        if self.coordinator.data is None:
            return None
        val = self.coordinator.data.get("backup_reserve")
        return float(val) if val is not None else None

    async def async_set_native_value(self, value: float) -> None:
        await self.coordinator.client.set_backup_reserve(int(value))
        await self.coordinator.async_request_refresh()
