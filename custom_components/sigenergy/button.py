"""Button platform for Sigenergy — V2X manual discharge start/stop."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.components.button import ButtonEntity

from .entity import SigenDCChargerStatusEntity

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

    from .coordinator import SigenSettingsCoordinator, SigenStatusCoordinator
    from .data import SigenConfigEntry


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SigenConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Sigenergy button entities."""
    data = entry.runtime_data
    dc_sns = data.status_coordinator.dc_sns()
    if not dc_sns:
        return
    station_id = data.client.station_id
    entities: list[ButtonEntity] = []
    for dc_sn in dc_sns:
        entities.extend(
            [
                SigenStartV2XButton(
                    data.status_coordinator,
                    data.settings_coordinator,
                    station_id,
                    dc_sn,
                    data.client,
                ),
                SigenStopV2XButton(
                    data.status_coordinator, station_id, dc_sn, data.client
                ),
            ]
        )
    async_add_entities(entities)


class SigenStartV2XButton(SigenDCChargerStatusEntity, ButtonEntity):
    """
    Start a V2X manual discharge session.

    Reads the current V2X Power Cap and V2X Duration from the settings
    coordinator before calling the API so both can be set in the UI first.
    """

    _attr_translation_key = "start_v2x_discharge"
    _attr_icon = "mdi:play-circle-outline"

    def __init__(
        self,
        status_coordinator: SigenStatusCoordinator,
        settings_coordinator: SigenSettingsCoordinator,
        station_id: str,
        dc_sn: str,
        client: Any,
    ) -> None:
        super().__init__(status_coordinator, station_id, dc_sn, "start_v2x_discharge")
        self._settings = settings_coordinator
        self._client = client

    async def async_press(self) -> None:
        await self._client.start_v2x_discharge(
            duration_minutes=self._settings.get_v2x_duration_minutes(self._dc_sn),
            power_cap_kw=self._settings.get_v2x_power_cap(self._dc_sn),
            dc_sn=self._dc_sn,
        )
        await self.coordinator.async_request_refresh()


class SigenStopV2XButton(SigenDCChargerStatusEntity, ButtonEntity):
    """Stop the current V2X manual discharge session."""

    _attr_translation_key = "stop_v2x_discharge"
    _attr_icon = "mdi:stop-circle-outline"

    def __init__(
        self,
        status_coordinator: SigenStatusCoordinator,
        station_id: str,
        dc_sn: str,
        client: Any,
    ) -> None:
        super().__init__(status_coordinator, station_id, dc_sn, "stop_v2x_discharge")
        self._client = client

    async def async_press(self) -> None:
        await self._client.stop_v2x_discharge(dc_sn=self._dc_sn)
        await self.coordinator.async_request_refresh()
