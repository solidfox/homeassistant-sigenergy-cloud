"""Button platform for Sigenergy — V2X controls and AIO power cycle."""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING, Any, Callable

from homeassistant.components.button import ButtonEntity
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.event import async_track_time_interval

from .const import DOMAIN, MODULE_EVDC, MODULE_STATION_SETTINGS
from .entity import SigenDCChargerStatusEntity, SigenStatusEntity
from .evdc_start_guard import EVDCStartReadyGate

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
    station_id = data.client.station_id
    entities: list[ButtonEntity] = []

    if data.status_coordinator.module_enabled(MODULE_STATION_SETTINGS):
        entities.append(
            SigenRestartAioButton(
                data.status_coordinator, station_id, data.client
            )
        )
        entities.append(
            SigenToggleAioPowerButton(
                data.status_coordinator, station_id, data.client
            )
        )

    if data.status_coordinator.module_enabled(MODULE_EVDC):
        dc_sns = data.status_coordinator.dc_sns()
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

    if entities:
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
        self._start_ready_gate = EVDCStartReadyGate(self, client, dc_sn)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return self._start_ready_gate.attributes()

    async def async_press(self) -> None:
        await self._start_ready_gate.wait()
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


class SigenRestartAioButton(SigenStatusEntity, ButtonEntity):
    """Power-cycle the SigenStor AIO to clear latched EVSE/SECC estcom faults."""

    _attr_translation_key = "restart_aio"
    _attr_icon = "mdi:restart-alert"
    _attr_entity_registry_enabled_default = True

    # After a cycle, cloud/HA can lag. Burst-refresh so alarm/SECC clear shows up.
    _POST_CYCLE_POLL_S = 2.0
    _POST_CYCLE_DURATION_S = 180.0

    def __init__(
        self,
        status_coordinator: SigenStatusCoordinator,
        station_id: str,
        client: Any,
    ) -> None:
        super().__init__(status_coordinator, station_id, "restart_aio")
        self._client = client
        self._post_cycle_refresh_unsub: Callable[[], None] | None = None
        self._attr_extra_state_attributes = {
            "description": (
                "Minimal AIO power-cycle via cloud POST /device/aio/on-off: off, "
                "poll until plant Power-off, wait for device/dcevse/status to change "
                "(EVDC reaction, ~10s observed), then powerOn=true and poll until "
                "running. Clears latched EVDC SECC state 9 / Charging fault. Drops "
                "site inverter/battery output briefly."
            ),
        }

    async def async_press(self) -> None:
        try:
            # off_dwell_s=0: turn back on as soon as home reports Power-off.
            result = await self._client.restart_aio(off_dwell_s=0.0, poll_s=2.0)
        except Exception as err:  # noqa: BLE001 - surface cloud failures in UI
            raise HomeAssistantError(f"Sigen AIO restart failed: {err}") from err
        if not result.get("powered_on"):
            raise HomeAssistantError(
                f"Sigen AIO restart did not restore power-on state: {result}"
            )
        self._attr_extra_state_attributes = {
            **(self._attr_extra_state_attributes or {}),
            "last_restart_result": result,
        }
        await self.coordinator.async_request_refresh()
        self._start_post_cycle_refresh_burst()

    def _start_post_cycle_refresh_burst(self) -> None:
        """Aggressively refresh coordinators so EVDC alarm/SECC clear is not stale."""
        if self._post_cycle_refresh_unsub is not None:
            self._post_cycle_refresh_unsub()
            self._post_cycle_refresh_unsub = None

        hass = self.hass
        status = self.coordinator
        settings = None
        for ent in hass.config_entries.async_entries(DOMAIN):
            runtime = getattr(ent, "runtime_data", None)
            if runtime is not None and getattr(runtime, "status_coordinator", None) is status:
                settings = getattr(runtime, "settings_coordinator", None)
                break

        started = hass.loop.time()
        interval = self._POST_CYCLE_POLL_S
        duration = self._POST_CYCLE_DURATION_S

        async def _tick(_now: Any = None) -> None:
            if hass.loop.time() - started > duration:
                if self._post_cycle_refresh_unsub is not None:
                    self._post_cycle_refresh_unsub()
                    self._post_cycle_refresh_unsub = None
                return
            await status.async_request_refresh()
            if settings is not None:
                await settings.async_request_refresh()

        hass.async_create_task(_tick())
        self._post_cycle_refresh_unsub = async_track_time_interval(
            hass, _tick, timedelta(seconds=interval)
        )

    async def async_will_remove_from_hass(self) -> None:
        if self._post_cycle_refresh_unsub is not None:
            self._post_cycle_refresh_unsub()
            self._post_cycle_refresh_unsub = None
        await super().async_will_remove_from_hass()


class SigenToggleAioPowerButton(SigenStatusEntity, ButtonEntity):
    """Single toggle of AIO power (mySigen device power on/off)."""

    _attr_translation_key = "toggle_aio_power"
    _attr_icon = "mdi:power"
    _attr_entity_registry_enabled_default = False

    def __init__(
        self,
        status_coordinator: SigenStatusCoordinator,
        station_id: str,
        client: Any,
    ) -> None:
        super().__init__(status_coordinator, station_id, "toggle_aio_power")
        self._client = client
        self._attr_extra_state_attributes = {
            "description": (
                "Toggles Sigen AIO power once via POST /device/aio/on-off. "
                "Disabled by default — prefer Restart AIO for recovery."
            ),
        }

    async def async_press(self) -> None:
        try:
            await self._client.toggle_aio_power()
        except Exception as err:  # noqa: BLE001
            raise HomeAssistantError(f"Sigen AIO power toggle failed: {err}") from err
        await self.coordinator.async_request_refresh()
