"""Select platform for Sigenergy — operational mode + DC charger mode."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.components.select import SelectEntity

from .entity import SigenDCChargerSettingsEntity, SigenSettingsEntity

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

    from .coordinator import SigenSettingsCoordinator
    from .data import SigenConfigEntry


# DC charger chargeMode int values observed on /device/charge/mode/dc.
# Forced/manual V2X uses separate timed-session endpoints, so it is intentionally
# modelled as buttons plus setpoint numbers rather than a persistent mode here.
DC_CHARGE_MODES: dict[str, int] = {
    "fast_charging": 0,
    "pv_surplus_charging": 1,
    "bidirectional_v2x": 2,
}
DC_CHARGE_MODES_REVERSE: dict[int, str] = {v: k for k, v in DC_CHARGE_MODES.items()}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SigenConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Sigenergy select entities."""
    data = entry.runtime_data
    entities: list[SelectEntity] = [
        SigenOperationalModeSelect(
            data.settings_coordinator,
            data.client.station_id,
        )
    ]
    for dc_sn in data.settings_coordinator.dc_sns():
        entities.append(
            SigenDCChargerModeSelect(
                data.settings_coordinator,
                data.client.station_id,
                dc_sn,
            )
        )
    async_add_entities(entities)


class SigenOperationalModeSelect(SigenSettingsEntity, SelectEntity):
    """Select entity for the station operational mode."""

    _attr_translation_key = "operational_mode"
    _attr_icon = "mdi:tune-variant"

    def __init__(
        self,
        coordinator: SigenSettingsCoordinator,
        station_id: str,
    ) -> None:
        super().__init__(coordinator, station_id, "operational_mode")

    @property
    def options(self) -> list[str]:
        return list(self.coordinator.available_modes.keys())

    @property
    def current_option(self) -> str | None:
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.get("operational_mode")

    async def async_select_option(self, option: str) -> None:
        mode_int, profile_id = self.coordinator.available_modes[option]
        await self.coordinator.client.set_operational_mode(mode_int, profile_id)
        self.coordinator.async_update_local_data({"operational_mode": option})


class SigenDCChargerModeSelect(SigenDCChargerSettingsEntity, SelectEntity):
    """Select entity for the DC charger's charge mode (Smart/Immediate/Bidirectional)."""

    _attr_translation_key = "dc_charger_mode"
    _attr_icon = "mdi:ev-station"
    _attr_options = list(DC_CHARGE_MODES.keys())

    def __init__(
        self,
        coordinator: SigenSettingsCoordinator,
        station_id: str,
        dc_sn: str,
    ) -> None:
        super().__init__(coordinator, station_id, dc_sn, "dc_charger_mode")

    @property
    def current_option(self) -> str | None:
        if self.coordinator.data is None:
            return None
        dc_data = (self.coordinator.data.get("dc_chargers") or {}).get(self._dc_sn, {})
        mode_data = dc_data.get("charge_mode") or {}
        mode_int = mode_data.get("chargeMode")
        if mode_int is None:
            return None
        return DC_CHARGE_MODES_REVERSE.get(int(mode_int))

    async def async_select_option(self, option: str) -> None:
        mode_int = DC_CHARGE_MODES[option]
        dc_data = ((self.coordinator.data or {}).get("dc_chargers") or {}).get(
            self._dc_sn, {}
        )
        current = dc_data.get("charge_mode") or {}
        kwargs: dict = {}
        if "enableFromPack" in current:
            kwargs["enable_from_pack"] = current["enableFromPack"]
        if "cutoffSocFromPack" in current:
            kwargs["cutoff_soc_from_pack"] = current["cutoffSocFromPack"]
        if "allowsDischargePower" in current:
            kwargs["allows_discharge_power"] = current["allowsDischargePower"]
        if "vehicleDischargeCutoffSoc" in current:
            kwargs["vehicle_discharge_cutoff_soc"] = current[
                "vehicleDischargeCutoffSoc"
            ]
        await self.coordinator.client.set_dc_charge_mode(
            mode_int, dc_sn=self._dc_sn, **kwargs
        )
        new_mode = dict(current)
        new_mode["chargeMode"] = mode_int
        self.coordinator.async_update_local_dc_data(
            self._dc_sn, {"charge_mode": new_mode}
        )
