"""Binary sensor platform for Sigenergy cloud status."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)

from .const import MODULE_EVDC
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
    if not data.status_coordinator.module_enabled(MODULE_EVDC):
        return

    entities: list[BinarySensorEntity] = []
    for dc_sn in data.status_coordinator.dc_sns():
        entities.append(
            SigenDCChargerPluggedInBinarySensor(
                data.status_coordinator,
                data.client.station_id,
                dc_sn,
            )
        )
        entities.append(
            SigenDCChargerTopologyOnlineBinarySensor(
                data.status_coordinator,
                data.client.station_id,
                dc_sn,
            )
        )
    async_add_entities(entities)


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


class SigenDCChargerTopologyOnlineBinarySensor(
    SigenDCChargerStatusEntity,
    BinarySensorEntity,
):
    """EVDC online state from mySigen topology deviceStatus/communicateStatus.

    This is the same view the app SigenStor detail panel uses. Prefer this over
    dcevse/status when deciding whether the EVDC has gone offline during an AIO
    power cycle.
    """

    _attr_translation_key = "dc_charger_topology_online"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_icon = "mdi:lan-connect"
    _attr_entity_registry_enabled_default = True

    def __init__(
        self,
        coordinator: SigenStatusCoordinator,
        station_id: str,
        dc_sn: str,
    ) -> None:
        super().__init__(coordinator, station_id, dc_sn, "dc_charger_topology_online")

    def _dc_data(self) -> dict[str, Any]:
        if self.coordinator.data is None:
            return {}
        return (self.coordinator.data.get("dc_chargers") or {}).get(self._dc_sn, {})

    @property
    def is_on(self) -> bool | None:
        offline = self._dc_data().get("topology_offline")
        if offline is None:
            return None
        return not bool(offline)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        dc = self._dc_data()
        return {
            "topology_device_status": dc.get("topology_device_status"),
            "topology_communicate_status": dc.get("topology_communicate_status"),
            "topology_offline": dc.get("topology_offline"),
            "topology_node_found": dc.get("topology_node_found"),
            "description": (
                "Online when topology communicateStatus=2 and deviceStatus is "
                "not offline/powerOff. Source: GET device/devicetreepanel/topology."
            ),
        }
