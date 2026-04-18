"""Sensor platform for Sigenergy — real-time energy flow."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import UnitOfPower, PERCENTAGE

from .entity import SigenEnergyEntity

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

    from .coordinator import SigenEnergyCoordinator
    from .data import SigenConfigEntry


@dataclass(frozen=True, kw_only=True)
class SigenSensorDescription(SensorEntityDescription):
    """Extends SensorEntityDescription with a data-key lookup."""

    data_key: str


SENSOR_DESCRIPTIONS: tuple[SigenSensorDescription, ...] = (
    SigenSensorDescription(
        key="pv_power",
        data_key="pv_power",
        translation_key="pv_power",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        icon="mdi:solar-power",
    ),
    SigenSensorDescription(
        key="battery_soc",
        data_key="battery_soc",
        translation_key="battery_soc",
        device_class=SensorDeviceClass.BATTERY,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
    ),
    SigenSensorDescription(
        key="battery_power",
        data_key="battery_power",
        translation_key="battery_power",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        icon="mdi:battery-charging",
    ),
    SigenSensorDescription(
        key="grid_import_power",
        data_key="grid_power",
        translation_key="grid_import_power",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        icon="mdi:transmission-tower-import",
    ),
    SigenSensorDescription(
        key="grid_export_power",
        data_key="grid_power",
        translation_key="grid_export_power",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        icon="mdi:transmission-tower-export",
    ),
    SigenSensorDescription(
        key="load_power",
        data_key="load_power",
        translation_key="load_power",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        icon="mdi:home-lightning-bolt",
    ),
)

EV_SENSOR_DESCRIPTION = SigenSensorDescription(
    key="ev_power",
    data_key="ev_power",
    translation_key="ev_power",
    device_class=SensorDeviceClass.POWER,
    state_class=SensorStateClass.MEASUREMENT,
    native_unit_of_measurement=UnitOfPower.KILO_WATT,
    icon="mdi:ev-station",
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SigenConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Sigenergy sensor entities."""
    data = entry.runtime_data
    coordinator = data.energy_coordinator
    station_id = data.client.station_id

    entities: list[SigenSensor] = [
        SigenSensor(coordinator, station_id, desc)
        for desc in SENSOR_DESCRIPTIONS
    ]

    if data.client.dc_sn:
        entities.append(SigenSensor(coordinator, station_id, EV_SENSOR_DESCRIPTION))

    async_add_entities(entities)


class SigenSensor(SigenEnergyEntity, SensorEntity):
    """A Sigenergy sensor reporting a real-time energy flow value."""

    entity_description: SigenSensorDescription

    def __init__(
        self,
        coordinator: SigenEnergyCoordinator,
        station_id: str,
        description: SigenSensorDescription,
    ) -> None:
        super().__init__(coordinator, station_id, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> float | None:
        if self.coordinator.data is None:
            return None
        raw = self.coordinator.data.get(self.entity_description.data_key)
        if raw is None:
            return None
        # grid_power sign convention:
        #   negative = importing from grid, positive = exporting to grid
        if self.entity_description.key == "grid_import_power":
            return max(0.0, -float(raw))
        if self.entity_description.key == "grid_export_power":
            return max(0.0, float(raw))
        return float(raw)
