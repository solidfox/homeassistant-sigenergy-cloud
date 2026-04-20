"""Sensor platform for Sigenergy — EV charge power (not available via Modbus)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import UnitOfPower

from .entity import SigenStatusEntity

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

    from .coordinator import SigenStatusCoordinator
    from .data import SigenConfigEntry


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SigenConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Sigenergy sensor entities."""
    data = entry.runtime_data
    async_add_entities([
        SigenEVPowerSensor(data.status_coordinator, data.client.station_id),
    ])


class SigenEVPowerSensor(SigenStatusEntity, SensorEntity):
    """EV charge power from the energy flow endpoint.

    Not available via the local Modbus integration, so polled from the cloud.
    """

    _attr_translation_key = "ev_power"
    _attr_device_class = SensorDeviceClass.POWER
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfPower.KILO_WATT
    _attr_icon = "mdi:ev-station"

    def __init__(self, coordinator: SigenStatusCoordinator, station_id: str) -> None:
        super().__init__(coordinator, station_id, "ev_power")

    @property
    def native_value(self) -> float | None:
        if self.coordinator.data is None:
            return None
        val = self.coordinator.data.get("ev_power")
        return float(val) if val is not None else None
