"""Binary sensor platform for Sigenergy cloud status."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)

from .entity import SigenDCChargerStatusEntity

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
    """Set up Sigenergy binary sensor entities."""
    data = entry.runtime_data
    async_add_entities(
        [
            SigenDCChargerPluggedInBinarySensor(
                data.status_coordinator,
                data.client.station_id,
                dc_sn,
            )
            for dc_sn in data.status_coordinator.dc_sns()
        ]
    )


class SigenDCChargerPluggedInBinarySensor(
    SigenDCChargerStatusEntity,
    BinarySensorEntity,
):
    """Vehicle-plug state reported by the DC charger plug-status endpoint."""

    _attr_translation_key = "dc_charger_plugged_in"
    _attr_device_class = BinarySensorDeviceClass.PLUG
    _attr_icon = "mdi:ev-plug-type2"

    def __init__(
        self,
        coordinator: SigenStatusCoordinator,
        station_id: str,
        dc_sn: str,
    ) -> None:
        super().__init__(coordinator, station_id, dc_sn, "dc_charger_plugged_in")

    @property
    def is_on(self) -> bool | None:
        if self.coordinator.data is None:
            return None
        dc_data = (self.coordinator.data.get("dc_chargers") or {}).get(self._dc_sn, {})
        value = dc_data.get("plugged_in")
        return bool(value) if value is not None else None
