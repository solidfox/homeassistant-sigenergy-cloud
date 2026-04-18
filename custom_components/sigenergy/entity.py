"""Base entity classes for Sigenergy."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import SigenEnergyCoordinator, SigenSettingsCoordinator


def _device_info(station_id: str) -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, station_id)},
        name="Sigenergy",
        manufacturer="Sigenergy",
    )


class SigenEnergyEntity(CoordinatorEntity[SigenEnergyCoordinator]):
    """Entity tied to the 30-second energy coordinator."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: SigenEnergyCoordinator,
        station_id: str,
        key: str,
    ) -> None:
        super().__init__(coordinator)
        self._station_id = station_id
        self._key = key
        self._attr_unique_id = f"{station_id}_{key}"
        self._attr_device_info = _device_info(station_id)


class SigenSettingsEntity(CoordinatorEntity[SigenSettingsCoordinator]):
    """Entity tied to the 5-minute settings coordinator."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: SigenSettingsCoordinator,
        station_id: str,
        key: str,
    ) -> None:
        super().__init__(coordinator)
        self._station_id = station_id
        self._key = key
        self._attr_unique_id = f"{station_id}_{key}"
        self._attr_device_info = _device_info(station_id)
