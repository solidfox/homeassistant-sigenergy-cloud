"""Base entity classes for Sigenergy."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import SigenSettingsCoordinator, SigenStatusCoordinator


def _station_device_info(station_id: str) -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, station_id)},
        name="Inverter Cloud",
        manufacturer="Sigenergy",
    )


def _dc_charger_device_info(
    station_id: str,
    dc_sn: str,
    dc_sns: list[str] | None = None,
) -> DeviceInfo:
    known_sns = dc_sns or []
    if not known_sns or len(known_sns) == 1 or known_sns[0] == dc_sn:
        name = "DC Charger"
    else:
        suffix = dc_sn[-4:] if len(dc_sn) >= 4 else dc_sn
        name = f"DC Charger {suffix}"

    return DeviceInfo(
        identifiers={(DOMAIN, f"{station_id}_{dc_sn}")},
        via_device=(DOMAIN, station_id),
        name=name,
        manufacturer="Sigenergy",
        model="DC Charger",
        serial_number=dc_sn,
    )


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
        self._attr_device_info = _station_device_info(station_id)


class SigenStatusEntity(CoordinatorEntity[SigenStatusCoordinator]):
    """Entity tied to the 30-second status coordinator."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: SigenStatusCoordinator,
        station_id: str,
        key: str,
    ) -> None:
        super().__init__(coordinator)
        self._station_id = station_id
        self._key = key
        self._attr_unique_id = f"{station_id}_{key}"
        self._attr_device_info = _station_device_info(station_id)


class SigenDCChargerSettingsEntity(SigenSettingsEntity):
    """Settings entity tied to a specific DC charger device."""

    def __init__(
        self,
        coordinator: SigenSettingsCoordinator,
        station_id: str,
        dc_sn: str,
        key: str,
    ) -> None:
        super().__init__(coordinator, station_id, f"{dc_sn}_{key}")
        self._dc_sn = dc_sn
        self._attr_device_info = _dc_charger_device_info(
            station_id, dc_sn, coordinator.dc_sns()
        )


class SigenDCChargerStatusEntity(SigenStatusEntity):
    """Status entity tied to a specific DC charger device."""

    def __init__(
        self,
        coordinator: SigenStatusCoordinator,
        station_id: str,
        dc_sn: str,
        key: str,
    ) -> None:
        super().__init__(coordinator, station_id, f"{dc_sn}_{key}")
        self._dc_sn = dc_sn
        self._attr_device_info = _dc_charger_device_info(
            station_id, dc_sn, coordinator.dc_sns()
        )
