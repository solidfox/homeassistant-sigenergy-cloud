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
from homeassistant.const import PERCENTAGE, UnitOfPower, UnitOfTime
from sigenergy_cloud import BatteryLevelSettings, PeakShavingSlot

from .entity import SigenDCChargerSettingsEntity, SigenSettingsEntity

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

    # DC charger settings + V2X session params (only when a DC charger is present)
    for dc_sn in coordinator.dc_sns():
        entities.append(SigenDCChargerPowerNumber(coordinator, station_id, dc_sn))
        entities.append(SigenDCChargerStopSOCNumber(coordinator, station_id, dc_sn))
        entities.append(
            SigenDCChargerDischargePowerNumber(coordinator, station_id, dc_sn)
        )
        entities.append(
            SigenDCChargerDischargeCutoffSOCNumber(coordinator, station_id, dc_sn)
        )
        entities.append(
            SigenDCChargerBatteryBoostCutoffSOCNumber(coordinator, station_id, dc_sn)
        )
        entities.append(SigenV2XPowerCapNumber(coordinator, station_id, dc_sn))
        entities.append(SigenV2XDurationNumber(coordinator, station_id, dc_sn))

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
            await self.coordinator.client.set_grid_export_limit(value, enabled=enabled)
        else:
            await self.coordinator.client.set_grid_import_limit(value, enabled=enabled)
        new_limit = dict(current)
        new_limit["enable"] = enabled
        new_limit["maxLimitationOwner"] = f"{value:.3f}"
        self.coordinator.async_update_local_data(
            {self.entity_description.data_key: new_limit}
        )


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
        settings: BatteryLevelSettings | None = self.coordinator.data.get(
            "battery_level"
        )
        if settings is None:
            return None
        return float(getattr(settings, self._SOC_FIELD[self.entity_description.key]))

    async def async_set_native_value(self, value: float) -> None:
        current: BatteryLevelSettings = self.coordinator.data["battery_level"]
        field = self._SOC_FIELD[self.entity_description.key]
        new_settings = BatteryLevelSettings(
            charge_soc=int(value) if field == "charge_soc" else current.charge_soc,
            discharge_soc=int(value)
            if field == "discharge_soc"
            else current.discharge_soc,
            peak_shaving_soc=int(value)
            if field == "peak_shaving_soc"
            else current.peak_shaving_soc,
            backup_soc=int(value) if field == "backup_soc" else current.backup_soc,
        )
        await self.coordinator.client.set_battery_levels(new_settings)
        self.coordinator.async_update_local_data({"battery_level": new_settings})


# ── Peak shaving slot numbers ─────────────────────────────────────────────────


class SigenPeakShavingSlotNumber(SigenSettingsEntity, NumberEntity):
    """
    Peak power cap for one peak shaving time slot (kW).

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
        new_schedule = schedule.with_slot(new_slot)
        await self.coordinator.client.set_peak_shaving_schedule(new_schedule)
        self.coordinator.async_update_local_data({"peak_shaving": new_schedule})


# ── DC charger settings ───────────────────────────────────────────────────────


class _SigenDCChargerSettingNumber(SigenDCChargerSettingsEntity, NumberEntity):
    """
    Shared base for the two charge-setting numbers — both write the full
    payload to POST /device/dcevse/charge/setting, so one field changing has to
    pass through the other field's current value.
    """

    _setting_field: str  # subclass overrides

    def __init__(
        self,
        coordinator: SigenSettingsCoordinator,
        station_id: str,
        dc_sn: str,
        key: str,
    ) -> None:
        super().__init__(coordinator, station_id, dc_sn, key)

    def _charge_setting(self) -> dict[str, Any]:
        dc_data = ((self.coordinator.data or {}).get("dc_chargers") or {}).get(
            self._dc_sn, {}
        )
        return dc_data.get("charge_setting") or {}

    @property
    def native_value(self) -> float | None:
        if self.coordinator.data is None:
            return None
        setting = self._charge_setting()
        val = setting.get(self._setting_field)
        return float(val) if val is not None else None

    async def async_set_native_value(self, value: float) -> None:
        current = self._charge_setting()
        power = float(current.get("allowedChargePower") or 0)
        soc = int(current.get("vehicleChargingCutoffSoc") or 100)
        if self._setting_field == "allowedChargePower":
            power = float(value)
        else:
            soc = int(value)
        await self.coordinator.client.set_dc_charge_setting(
            allowed_charge_power=power,
            vehicle_charging_cutoff_soc=soc,
            dc_sn=self._dc_sn,
        )
        new_setting = dict(current)
        new_setting["allowedChargePower"] = power
        new_setting["vehicleChargingCutoffSoc"] = soc
        self.coordinator.async_update_local_dc_data(
            self._dc_sn, {"charge_setting": new_setting}
        )


class SigenDCChargerPowerNumber(_SigenDCChargerSettingNumber):
    """Max charging power for the DC charger (kW)."""

    _attr_translation_key = "dc_charger_max_power"
    _attr_device_class = NumberDeviceClass.POWER
    _attr_native_unit_of_measurement = UnitOfPower.KILO_WATT
    _attr_native_min_value = 1.0
    _attr_native_max_value = 25.0
    _attr_native_step = 0.5
    _attr_mode = NumberMode.BOX
    _attr_icon = "mdi:flash"
    _setting_field = "allowedChargePower"

    def __init__(
        self, coordinator: SigenSettingsCoordinator, station_id: str, dc_sn: str
    ) -> None:
        super().__init__(coordinator, station_id, dc_sn, "dc_charger_max_power")


class SigenDCChargerStopSOCNumber(_SigenDCChargerSettingNumber):
    """Stop charging when the EV reaches this SOC (%)."""

    _attr_translation_key = "dc_charger_stop_soc"
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_native_min_value = 50.0
    _attr_native_max_value = 100.0
    _attr_native_step = 1.0
    _attr_mode = NumberMode.BOX
    _attr_icon = "mdi:battery-charging-100"
    _setting_field = "vehicleChargingCutoffSoc"

    def __init__(
        self, coordinator: SigenSettingsCoordinator, station_id: str, dc_sn: str
    ) -> None:
        super().__init__(coordinator, station_id, dc_sn, "dc_charger_stop_soc")


# ── DC charger mode setting numbers ───────────────────────────────────────────


class _SigenDCChargerModeNumber(SigenDCChargerSettingsEntity, NumberEntity):
    """Shared base for settings written through /device/charge/mode/dc."""

    _mode_field: str
    _settings_charge_mode: int | None = None

    def __init__(
        self,
        coordinator: SigenSettingsCoordinator,
        station_id: str,
        dc_sn: str,
        key: str,
    ) -> None:
        super().__init__(coordinator, station_id, dc_sn, key)

    def _charge_mode(self) -> dict[str, Any]:
        dc_data = ((self.coordinator.data or {}).get("dc_chargers") or {}).get(
            self._dc_sn, {}
        )
        return dc_data.get("charge_mode") or {}

    def _charge_setting(self) -> dict[str, Any]:
        dc_data = ((self.coordinator.data or {}).get("dc_chargers") or {}).get(
            self._dc_sn, {}
        )
        return dc_data.get("charge_setting") or {}

    def _soc_range(self) -> dict[str, Any]:
        return (self.coordinator.data or {}).get("dc_charge_soc_range") or {}

    @property
    def available(self) -> bool:
        return (
            super().available
            and self.coordinator.data is not None
            and self._mode_field in self._charge_mode()
        )

    @property
    def native_value(self) -> float | None:
        if self.coordinator.data is None:
            return None
        value = self._charge_mode().get(self._mode_field)
        return float(value) if value is not None else None

    async def _write_charge_mode(self, value: float) -> None:
        current = self._charge_mode()
        charge_mode = int(current.get("chargeMode") or 0)
        write_charge_mode = (
            self._settings_charge_mode
            if self._settings_charge_mode is not None
            else charge_mode
        )
        kwargs: dict[str, Any] = {}
        field_map = {
            "enable_from_pack": "enableFromPack",
            "cutoff_soc_from_pack": "cutoffSocFromPack",
            "allows_discharge_power": "allowsDischargePower",
            "vehicle_discharge_cutoff_soc": "vehicleDischargeCutoffSoc",
        }
        for arg_name, field_name in field_map.items():
            if current.get(field_name) is not None:
                kwargs[arg_name] = current[field_name]

        if self._mode_field == "vehicleDischargeCutoffSoc":
            kwargs["vehicle_discharge_cutoff_soc"] = int(value)
        else:
            kwargs[self._api_argument] = float(value)

        await self.coordinator.client.set_dc_charge_mode(
            write_charge_mode,
            dc_sn=self._dc_sn,
            **kwargs,
        )
        if write_charge_mode != charge_mode:
            await self.coordinator.client.set_dc_charge_mode(
                charge_mode,
                dc_sn=self._dc_sn,
            )
        new_mode = dict(current)
        new_mode["chargeMode"] = charge_mode
        new_mode[self._mode_field] = (
            int(value)
            if self._mode_field == "vehicleDischargeCutoffSoc"
            else float(value)
        )
        self.coordinator.async_update_local_dc_data(
            self._dc_sn, {"charge_mode": new_mode}
        )

    async def async_set_native_value(self, value: float) -> None:
        await self._write_charge_mode(value)


class SigenDCChargerDischargePowerNumber(_SigenDCChargerModeNumber):
    """Maximum bidirectional discharge power in kW."""

    _attr_translation_key = "dc_charger_max_discharge_power"
    _attr_device_class = NumberDeviceClass.POWER
    _attr_native_unit_of_measurement = UnitOfPower.KILO_WATT
    _attr_native_min_value = 0.0
    _attr_native_step = 0.1
    _attr_mode = NumberMode.BOX
    _attr_icon = "mdi:flash-outline"
    _mode_field = "allowsDischargePower"
    _api_argument = "allows_discharge_power"
    _settings_charge_mode = 2

    def __init__(
        self, coordinator: SigenSettingsCoordinator, station_id: str, dc_sn: str
    ) -> None:
        super().__init__(
            coordinator, station_id, dc_sn, "dc_charger_max_discharge_power"
        )

    @property
    def native_max_value(self) -> float:
        setting = self._charge_setting()
        return float(setting.get("ratedPower") or 25.0)


class SigenDCChargerDischargeCutoffSOCNumber(_SigenDCChargerModeNumber):
    """Stop bidirectional discharge when the EV reaches this SOC."""

    _attr_translation_key = "dc_charger_discharge_cutoff_soc"
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_native_step = 1.0
    _attr_mode = NumberMode.BOX
    _attr_icon = "mdi:battery-arrow-down-outline"
    _mode_field = "vehicleDischargeCutoffSoc"
    _api_argument = "vehicle_discharge_cutoff_soc"
    _settings_charge_mode = 2

    def __init__(
        self, coordinator: SigenSettingsCoordinator, station_id: str, dc_sn: str
    ) -> None:
        super().__init__(
            coordinator, station_id, dc_sn, "dc_charger_discharge_cutoff_soc"
        )

    @property
    def native_min_value(self) -> float:
        current = self._charge_mode()
        return float(
            current.get("minimumDischargeCutoffSoc")
            or self._soc_range().get("socLowerLimit")
            or 0.0
        )

    @property
    def native_max_value(self) -> float:
        current = self._charge_mode()
        return float(
            current.get("maximumDischargeCutoffSoc")
            or self._soc_range().get("socUpperLimit")
            or 100.0
        )


class SigenDCChargerBatteryBoostCutoffSOCNumber(_SigenDCChargerModeNumber):
    """SOC floor used when battery boost is enabled for charging."""

    _attr_translation_key = "dc_charger_battery_boost_cutoff_soc"
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_native_step = 1.0
    _attr_mode = NumberMode.BOX
    _attr_icon = "mdi:battery-plus"
    _mode_field = "cutoffSocFromPack"
    _api_argument = "cutoff_soc_from_pack"

    def __init__(
        self, coordinator: SigenSettingsCoordinator, station_id: str, dc_sn: str
    ) -> None:
        super().__init__(
            coordinator, station_id, dc_sn, "dc_charger_battery_boost_cutoff_soc"
        )

    @property
    def native_min_value(self) -> float:
        return float(self._soc_range().get("socLowerLimit") or 0.0)

    @property
    def native_max_value(self) -> float:
        return float(self._soc_range().get("socUpperLimit") or 100.0)


# ── V2X power cap ─────────────────────────────────────────────────────────────


class SigenV2XPowerCapNumber(SigenDCChargerSettingsEntity, NumberEntity):
    """
    Maximum discharge power cap for a V2X session (kW).

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

    def __init__(
        self, coordinator: SigenSettingsCoordinator, station_id: str, dc_sn: str
    ) -> None:
        super().__init__(coordinator, station_id, dc_sn, "v2x_power_cap")

    @property
    def native_value(self) -> float:
        return self.coordinator.get_v2x_power_cap(self._dc_sn) or 0.0

    async def async_set_native_value(self, value: float) -> None:
        self.coordinator.set_v2x_power_cap(self._dc_sn, value if value > 0 else None)
        self.async_write_ha_state()


class SigenV2XDurationNumber(SigenDCChargerSettingsEntity, NumberEntity):
    """
    Duration of a V2X manual discharge session (minutes).

    Set this before pressing Start V2X Discharge. Default is 600 minutes.
    """

    _attr_translation_key = "v2x_duration"
    _attr_native_unit_of_measurement = UnitOfTime.MINUTES
    _attr_native_min_value = 5.0
    _attr_native_max_value = 720.0
    _attr_native_step = 5.0
    _attr_mode = NumberMode.BOX
    _attr_icon = "mdi:timer-outline"

    def __init__(
        self, coordinator: SigenSettingsCoordinator, station_id: str, dc_sn: str
    ) -> None:
        super().__init__(coordinator, station_id, dc_sn, "v2x_duration")

    @property
    def native_value(self) -> float:
        return float(self.coordinator.get_v2x_duration_minutes(self._dc_sn))

    async def async_set_native_value(self, value: float) -> None:
        self.coordinator.set_v2x_duration_minutes(self._dc_sn, int(value))
        self.async_write_ha_state()
