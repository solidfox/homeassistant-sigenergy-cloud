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
        entities.append(
            SigenRefreshDeviceStatusButton(
                data.status_coordinator, station_id
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


class SigenRefreshDeviceStatusButton(SigenStatusEntity, ButtonEntity):
    """Force an immediate topology + EVDC status poll (for automations)."""

    _attr_translation_key = "refresh_device_status"
    _attr_icon = "mdi:refresh"
    _attr_entity_registry_enabled_default = True

    def __init__(
        self,
        status_coordinator: SigenStatusCoordinator,
        station_id: str,
    ) -> None:
        super().__init__(status_coordinator, station_id, "refresh_device_status")
        self._attr_extra_state_attributes = {
            "description": (
                "Forces topology deviceStatus/communicateStatus and EVDC "
                "status endpoints to refresh now, then keeps a short fast-poll "
                "window. Prefer service sigenergy.refresh_device_status for "
                "automations."
            ),
        }

    async def async_press(self) -> None:
        await self.coordinator.async_request_device_status_poll(
            source="manual_button",
            duration_s=60.0,
            enable_fast_poll=True,
        )


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
                "poll until plant Power-off, wait until topology reports EVDC "
                "offline (device/devicetreepanel/topology deviceStatus / "
                "communicateStatus), then powerOn=true and poll until running. "
                "Clears latched EVDC SECC state 9 / Charging fault. Drops site "
                "inverter/battery output briefly. Never leaves plant powered off."
            ),
        }

    async def async_press(self) -> None:
        # Aggressive deviceStatus polling while power is changing.
        self.coordinator.start_aio_power_fast_poll(
            source="aio_power_cycle", duration_s=self._POST_CYCLE_DURATION_S
        )
        await self.coordinator.async_request_refresh()
        try:
            result = await self._client.restart_aio(
                off_dwell_s=0.0,
                poll_s=2.0,
                wait_evdc_offline=True,
                evdc_offline_wait_s=120.0,
            )
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
        await self.coordinator.async_request_device_status_poll(
            source="aio_power_cycle",
            duration_s=self._POST_CYCLE_DURATION_S,
            enable_fast_poll=True,
        )
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
            # Keep topology deviceStatus forced during the burst window.
            status.request_force_device_status_poll()
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
                "Disabled by default — prefer Restart AIO for recovery. "
                "Triggers aggressive topology deviceStatus polling afterward."
            ),
        }

    async def async_press(self) -> None:
        self.coordinator.start_aio_power_fast_poll(
            source="aio_power_toggle", duration_s=180.0
        )
        try:
            await self._client.toggle_aio_power()
        except Exception as err:  # noqa: BLE001
            raise HomeAssistantError(f"Sigen AIO power toggle failed: {err}") from err
        await self.coordinator.async_request_device_status_poll(
            source="aio_power_toggle",
            duration_s=180.0,
            enable_fast_poll=True,
        )
