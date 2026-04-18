"""Button platform for Sigenergy — V2X discharge controls."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.components.button import ButtonEntity
from homeassistant.helpers.device_registry import DeviceInfo

from .const import DOMAIN

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

    from .data import SigenConfigEntry
    from .sigen import Sigen


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SigenConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Sigenergy button entities (only if DC charger is present)."""
    data = entry.runtime_data
    if not data.client.dc_sn:
        return

    station_id = data.client.station_id
    async_add_entities([
        SigenStartV2XButton(data.client, station_id),
        SigenStopV2XButton(data.client, station_id),
    ])


class SigenV2XButton(ButtonEntity):
    """Base class for V2X discharge buttons."""

    _attr_has_entity_name = True

    def __init__(self, client: Sigen, station_id: str, key: str) -> None:
        self._client = client
        self._attr_unique_id = f"{station_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, station_id)},
            name="Sigenergy",
            manufacturer="Sigenergy",
        )


class SigenStartV2XButton(SigenV2XButton):
    """Start V2X (vehicle-to-grid) discharge session."""

    _attr_translation_key = "start_v2x_discharge"
    _attr_icon = "mdi:car-battery"

    def __init__(self, client: Sigen, station_id: str) -> None:
        super().__init__(client, station_id, "start_v2x_discharge")

    async def async_press(self, **kwargs: Any) -> None:
        # Default: 120 minutes, no power cap
        await self._client.start_v2x_discharge(duration_minutes=120, power_cap_kw=None)


class SigenStopV2XButton(SigenV2XButton):
    """Stop the current V2X discharge session."""

    _attr_translation_key = "stop_v2x_discharge"
    _attr_icon = "mdi:car-off"

    def __init__(self, client: Sigen, station_id: str) -> None:
        super().__init__(client, station_id, "stop_v2x_discharge")

    async def async_press(self, **kwargs: Any) -> None:
        await self._client.stop_v2x_discharge()
