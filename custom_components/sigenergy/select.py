"""Select platform for Sigenergy — operational mode selector."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.components.select import SelectEntity

from .entity import SigenSettingsEntity

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

    from .coordinator import SigenSettingsCoordinator
    from .data import SigenConfigEntry


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SigenConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Sigenergy select entities."""
    data = entry.runtime_data
    async_add_entities([
        SigenOperationalModeSelect(
            data.settings_coordinator,
            data.client.station_id,
        )
    ])


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
        await self.coordinator.async_request_refresh()
