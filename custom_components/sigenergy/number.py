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
from .sigen.peak_shaving import PeakShavingSlot

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

    from .coordinator import SigenSettingsCoordinator
    from .data import SigenConfigEntry


@dataclass(frozen=True, kw_only=True)
class SigenNumberDescription(NumberEntityDescription):
    data_key: str


# ── Grid power limits ─────────────────────────────────────────────────────────

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

# ── Battery SOC levels ────────────────────────────────────────────────────────

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


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SigenConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Sigenergy number entities."""
    data = entry.runtime_data
    coordinator = data.settings_coordinator
    station_id = data.client.station_id

    entities: list[NumberEntity] = []

    for desc in POWER_LIMIT_NUMBERS:
        entities.append(SigenPowerLimitNumber(coordinator, station_id, desc))
    for desc in BATTERY_NUMBERS:
        entities.append(SigenBatterySOCNumber(coordinator, station_id, desc))

    # Peak shaving slot numbers — one per slot in the current schedule
    schedule = coordinator.data.get("peak_shaving") if coordinator.data else None
    if schedule:
        for slot in schedule.slots:
            entities.append(SigenPeakShavingSlotNumber(coordinator, station_id, slot))

    # V2X power cap (only relevant when a DC charger is present)
    if data.client.dc_sn:
        entities.append(SigenV2XPowerCapNumber(coordinator, station_id))

    async_add_entities(entities)


# ── Grid limit numbers ────────────────────────────────────────────────────────

class SigenPowerLimitNumber(SigenSettingsEntity, NumberEntity):
    """Grid export or import power limit in kW."""

    entity_description: SigenNumberDescription

    def __init__(
        self,
        coordinator: SigenSettingsCoordinator,
        station_id: str,
        description: SigenNumberDescription,
    ) -> None:
        super().__init__(coordinator, station_id, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> float | None:
        if self.coordinator.data is None:
            return None
        limit_data = self.coordinator.data.get(self.entity_description.data_key)
        if not limit_data:
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


# ── Battery SOC numbers ───────────────────────────────────────────────────────

class SigenBatterySOCNumber(SigenSettingsEntity, NumberEntity):
    """One of the four battery SOC limit fields."""

    _SOC_FIELD: dict[str, str] = {
        "battery_charge_soc": "charge_soc",
        "battery_discharge_soc": "discharge_soc",
        "battery_peak_shaving_soc": "peak_shaving_soc",
        "battery_backup_soc": "backup_soc",
    }

    entity_description: SigenNumberDescription

    def __init__(
        self,
        coordinator: SigenSettingsCoordinator,
        station_id: str,
        description: SigenNumberDescription,
    ) -> None:
        super().__init__(coordinator, station_id, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> float | None:
        if self.coordinator.data is None:
            return None
        settings: BatteryLevelSettings | None = self.coordinator.data.get("battery_level")
        if settings is None:
            return None
        return float(getattr(settings, self._SOC_FIELD[self.entity_description.key]))

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


# ── Peak shaving slot numbers ─────────────────────────────────────────────────

class SigenPeakShavingSlotNumber(SigenSettingsEntity, NumberEntity):
    """Peak power cap for one peak shaving time slot (kW).

    Named after the slot's time range so it's self-describing in the UI.
    When the schedule changes in the Sigenergy app, the entity name updates
    on the next settings poll (5 min).
    """

    _attr_device_class = NumberDeviceClass.POWER
    _attr_native_unit_of_measurement = UnitOfPower.KILO_WATT
    _attr_native_min_value = 0.0
    _attr_native_max_value = 100.0
    _attr_native_step = 0.1
    _attr_mode = NumberMode.BOX
    _attr_icon = "mdi:chart-bell-curve"

    def __init__(
        self,
        coordinator: SigenSettingsCoordinator,
        station_id: str,
        slot: PeakShavingSlot,
    ) -> None:
        super().__init__(coordinator, station_id, f"peak_shaving_slot_{slot.index}")
        self._slot_index = slot.index
        # Initial name from first-fetched slot; updates via the name property below
        self._initial_start = slot.start_time
        self._initial_end = slot.end_time

    @property
    def name(self) -> str:
        """Return the slot's time range as the entity name."""
        if self.coordinator.data:
            schedule = self.coordinator.data.get("peak_shaving")
            if schedule:
                slot = next(
                    (s for s in schedule.slots if s.index == self._slot_index), None
                )
                if slot:
                    return f"Peak Shaving {slot.start_time}–{slot.end_time}"
        return f"Peak Shaving {self._initial_start}–{self._initial_end}"

    @property
    def native_value(self) -> float | None:
        if self.coordinator.data is None:
            return None
        schedule = self.coordinator.data.get("peak_shaving")
        if not schedule:
            return None
        slot = next((s for s in schedule.slots if s.index == self._slot_index), None)
        return slot.peak_power_kw if slot else None

    @property
    def available(self) -> bool:
        if not super().available or self.coordinator.data is None:
            return False
        schedule = self.coordinator.data.get("peak_shaving")
        if not schedule:
            return False
        return any(s.index == self._slot_index for s in schedule.slots)

    async def async_set_native_value(self, value: float) -> None:
        schedule = self.coordinator.data["peak_shaving"]
        current_slot = next(
            (s for s in schedule.slots if s.index == self._slot_index), None
        )
        if current_slot is None:
            return
        new_slot = PeakShavingSlot(
            index=current_slot.index,
            which_days=current_slot.which_days,
            start_time=current_slot.start_time,
            end_time=current_slot.end_time,
            peak_power_kw=value,
        )
        await self.coordinator.client.set_peak_shaving_slot(new_slot)
        await self.coordinator.async_request_refresh()


# ── V2X power cap ─────────────────────────────────────────────────────────────

class SigenV2XPowerCapNumber(SigenSettingsEntity, NumberEntity):
    """Maximum discharge power cap for a V2X session (kW).

    Set this before turning on the V2X Discharge switch.
    0 means no cap (full available power). The value is held in the
    coordinator and passed to start_v2x_discharge() when the switch fires.
    """

    _attr_translation_key = "v2x_power_cap"
    _attr_device_class = NumberDeviceClass.POWER
    _attr_native_unit_of_measurement = UnitOfPower.KILO_WATT
    _attr_native_min_value = 0.0
    _attr_native_max_value = 50.0
    _attr_native_step = 0.5
    _attr_mode = NumberMode.BOX
    _attr_icon = "mdi:car-electric"

    def __init__(self, coordinator: SigenSettingsCoordinator, station_id: str) -> None:
        super().__init__(coordinator, station_id, "v2x_power_cap")

    @property
    def native_value(self) -> float:
        return self.coordinator.v2x_power_cap_kw or 0.0

    async def async_set_native_value(self, value: float) -> None:
        self.coordinator.v2x_power_cap_kw = value if value > 0 else None
        self.async_write_ha_state()
