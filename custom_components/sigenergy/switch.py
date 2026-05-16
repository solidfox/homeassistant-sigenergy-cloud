"""Switch platform for Sigenergy — binary controls with polled state."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

from homeassistant.components.switch import SwitchDeviceClass, SwitchEntity
from homeassistant.exceptions import HomeAssistantError

from .entity import (
    SigenDCChargerSettingsEntity,
    SigenDCChargerStatusEntity,
    SigenSettingsEntity,
)

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

    from .coordinator import (
        SigenSettingsCoordinator,
        SigenStatusCoordinator,
    )
    from .data import SigenConfigEntry


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SigenConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Sigenergy switch entities."""
    data = entry.runtime_data
    station_id = data.client.station_id

    entities: list[SwitchEntity] = [
        SigenExportLimitSwitch(data.settings_coordinator, station_id),
        SigenImportLimitSwitch(data.settings_coordinator, station_id),
        SigenBatteryExportSwitch(data.settings_coordinator, station_id),
    ]

    for dc_sn in data.settings_coordinator.dc_sns():
        entities.append(
            SigenDCChargerBatteryBoostSwitch(
                data.settings_coordinator,
                station_id,
                dc_sn,
            )
        )

    for dc_sn in data.status_coordinator.dc_sns():
        entities.append(
            SigenDCChargerSwitch(
                data.status_coordinator, station_id, dc_sn, data.client
            )
        )
        entities.append(
            SigenV2XDischargeSwitch(
                data.status_coordinator, station_id, dc_sn, data.client
            )
        )

    async_add_entities(entities)


# ── Settings-backed switches ──────────────────────────────────────────────────


class SigenExportLimitSwitch(SigenSettingsEntity, SwitchEntity):
    """Enable/disable the grid export power limit."""

    _attr_translation_key = "export_limit_enabled"
    _attr_device_class = SwitchDeviceClass.SWITCH
    _attr_icon = "mdi:transmission-tower-export"

    def __init__(self, coordinator: SigenSettingsCoordinator, station_id: str) -> None:
        super().__init__(coordinator, station_id, "export_limit_enabled")

    @property
    def is_on(self) -> bool | None:
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.get("export_limit", {}).get("enable")

    async def async_turn_on(self, **kwargs: Any) -> None:
        current = self.coordinator.data.get("export_limit", {})
        limit_kw = float(current.get("maxLimitationOwner") or 0)
        await self.coordinator.client.set_grid_export_limit(limit_kw, enabled=True)
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        current = self.coordinator.data.get("export_limit", {})
        limit_kw = float(current.get("maxLimitationOwner") or 0)
        await self.coordinator.client.set_grid_export_limit(limit_kw, enabled=False)
        await self.coordinator.async_request_refresh()


class SigenImportLimitSwitch(SigenSettingsEntity, SwitchEntity):
    """Enable/disable the grid import power limit."""

    _attr_translation_key = "import_limit_enabled"
    _attr_device_class = SwitchDeviceClass.SWITCH
    _attr_icon = "mdi:transmission-tower-import"

    def __init__(self, coordinator: SigenSettingsCoordinator, station_id: str) -> None:
        super().__init__(coordinator, station_id, "import_limit_enabled")

    @property
    def is_on(self) -> bool | None:
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.get("import_limit", {}).get("enable")

    async def async_turn_on(self, **kwargs: Any) -> None:
        current = self.coordinator.data.get("import_limit", {})
        limit_kw = float(current.get("maxLimitationOwner") or 0)
        await self.coordinator.client.set_grid_import_limit(limit_kw, enabled=True)
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        current = self.coordinator.data.get("import_limit", {})
        limit_kw = float(current.get("maxLimitationOwner") or 0)
        await self.coordinator.client.set_grid_import_limit(limit_kw, enabled=False)
        await self.coordinator.async_request_refresh()


class SigenBatteryExportSwitch(SigenSettingsEntity, SwitchEntity):
    """Allow or block battery-to-grid export."""

    _attr_translation_key = "battery_export_enabled"
    _attr_device_class = SwitchDeviceClass.SWITCH
    _attr_icon = "mdi:battery-arrow-right"

    def __init__(self, coordinator: SigenSettingsCoordinator, station_id: str) -> None:
        super().__init__(coordinator, station_id, "battery_export_enabled")

    @property
    def is_on(self) -> bool | None:
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.get("battery_export", {}).get("ownerSetEnable")

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.client.set_battery_export_limitation(True)
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.client.set_battery_export_limitation(False)
        await self.coordinator.async_request_refresh()


# ── DC charger setting switches ───────────────────────────────────────────────


class SigenDCChargerBatteryBoostSwitch(SigenDCChargerSettingsEntity, SwitchEntity):
    """Enable or disable battery boost for the current DC charge mode."""

    _attr_translation_key = "dc_charger_battery_boost"
    _attr_device_class = SwitchDeviceClass.SWITCH
    _attr_icon = "mdi:battery-plus"

    def __init__(
        self, coordinator: SigenSettingsCoordinator, station_id: str, dc_sn: str
    ) -> None:
        super().__init__(coordinator, station_id, dc_sn, "dc_charger_battery_boost")

    def _charge_mode(self) -> dict[str, Any]:
        dc_data = ((self.coordinator.data or {}).get("dc_chargers") or {}).get(
            self._dc_sn, {}
        )
        return dc_data.get("charge_mode") or {}

    @property
    def available(self) -> bool:
        return (
            super().available
            and self.coordinator.data is not None
            and "enableFromPack" in self._charge_mode()
        )

    @property
    def is_on(self) -> bool | None:
        if self.coordinator.data is None:
            return None
        current = self._charge_mode()
        value = current.get("enableFromPack")
        return bool(value) if value is not None else None

    async def _set_enabled(self, enabled: bool) -> None:
        current = self._charge_mode()
        charge_mode = int(current.get("chargeMode") or 0)
        kwargs: dict[str, Any] = {
            "enable_from_pack": enabled,
        }
        if current.get("cutoffSocFromPack") is not None:
            kwargs["cutoff_soc_from_pack"] = float(current["cutoffSocFromPack"])
        if current.get("allowsDischargePower") is not None:
            kwargs["allows_discharge_power"] = float(current["allowsDischargePower"])
        if current.get("vehicleDischargeCutoffSoc") is not None:
            kwargs["vehicle_discharge_cutoff_soc"] = int(
                current["vehicleDischargeCutoffSoc"]
            )
        await self.coordinator.client.set_dc_charge_mode(
            charge_mode,
            dc_sn=self._dc_sn,
            **kwargs,
        )
        await self.coordinator.async_request_refresh()

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._set_enabled(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._set_enabled(False)


# ── Status-backed switches (polled every 30 s) ────────────────────────────────

_DC_CHARGER_PENDING_TIMEOUT = 5 * 60


class SigenDCChargerSwitch(SigenDCChargerStatusEntity, SwitchEntity):
    """Start/stop DC charger with a pending target state."""

    _attr_translation_key = "dc_charger_enabled"
    _attr_device_class = SwitchDeviceClass.SWITCH
    _attr_icon = "mdi:ev-plug-type2"

    def __init__(
        self,
        coordinator: SigenStatusCoordinator,
        station_id: str,
        dc_sn: str,
        client: Any,
    ) -> None:
        super().__init__(coordinator, station_id, dc_sn, "dc_charger_enabled")
        self._client = client
        self._pending_target: bool | None = None
        self._pending_since: float | None = None
        self._pending_confirmations = 0
        self._pending_last_data_id: int | None = None

    def _actual_is_on(self) -> bool | None:
        if self.coordinator.data is None:
            return None
        dc_data = (self.coordinator.data.get("dc_chargers") or {}).get(self._dc_sn, {})
        value = dc_data.get("is_charging")
        return bool(value) if value is not None else None

    def _active_pending_target(self) -> bool | None:
        """Return the pending target if still waiting for telemetry."""
        if self._pending_target is None:
            return None

        actual = self._actual_is_on()
        if actual is self._pending_target:
            data_id = id(self.coordinator.data)
            if data_id != self._pending_last_data_id:
                self._pending_last_data_id = data_id
                self._pending_confirmations += 1

            confirmations_needed = 2
            if self._pending_confirmations >= confirmations_needed:
                self._clear_pending()
                return None
        else:
            self._pending_confirmations = 0
            self._pending_last_data_id = None

        if (
            self._pending_since is not None
            and time.monotonic() - self._pending_since > _DC_CHARGER_PENDING_TIMEOUT
        ):
            self._clear_pending()
            return None

        return self._pending_target

    def _set_pending(self, target: bool) -> None:
        self._pending_target = target
        self._pending_since = time.monotonic()
        self._pending_confirmations = 0
        self._pending_last_data_id = None
        self.coordinator.set_fast_polling(self._attr_unique_id, True)

    def _clear_pending(self) -> None:
        if self._pending_target is not None:
            self.coordinator.set_fast_polling(self._attr_unique_id, False)
        self._pending_target = None
        self._pending_since = None
        self._pending_confirmations = 0
        self._pending_last_data_id = None

    def _raise_if_rejected(self, response: dict[str, Any]) -> None:
        data = response.get("data")
        if not isinstance(data, dict):
            return
        if data.get("successful", True):
            return
        error_code = data.get("errorCode") or "unknown"
        raise HomeAssistantError(f"Sigenergy rejected charger command: {error_code}")

    @property
    def is_on(self) -> bool | None:
        pending_target = self._active_pending_target()
        if pending_target is not None:
            return pending_target
        return self._actual_is_on()

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        pending_target = self._active_pending_target()
        if pending_target is None:
            return {}
        pending_for = 0
        if self._pending_since is not None:
            pending_for = int(time.monotonic() - self._pending_since)
        return {
            "pending": True,
            "target_state": "on" if pending_target else "off",
            "pending_for_seconds": pending_for,
            "pending_confirmations": self._pending_confirmations,
        }

    async def async_turn_on(self, **kwargs: Any) -> None:
        response = await self._client.set_dc_charge_enabled(True, dc_sn=self._dc_sn)
        self._raise_if_rejected(response)
        self._set_pending(True)
        self.async_write_ha_state()
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        response = await self._client.set_dc_charge_enabled(False, dc_sn=self._dc_sn)
        self._raise_if_rejected(response)
        self._set_pending(False)
        self.async_write_ha_state()
        await self.coordinator.async_request_refresh()


class SigenV2XDischargeSwitch(SigenDCChargerStatusEntity, SwitchEntity):
    """Enable or disable V2X discharge for a DC charger."""

    _attr_translation_key = "v2x_discharge"
    _attr_device_class = SwitchDeviceClass.SWITCH
    _attr_icon = "mdi:car-electric"

    def __init__(
        self,
        coordinator: SigenStatusCoordinator,
        station_id: str,
        dc_sn: str,
        client: Any,
    ) -> None:
        super().__init__(coordinator, station_id, dc_sn, "v2x_discharge_enabled")
        self._client = client

    def _dc_data(self) -> dict[str, Any]:
        if self.coordinator.data is None:
            return {}
        return (self.coordinator.data.get("dc_chargers") or {}).get(self._dc_sn, {})

    @property
    def is_on(self) -> bool | None:
        value = self._dc_data().get("v2x_discharge_enabled")
        return bool(value) if value is not None else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        dc_data = self._dc_data()
        attrs: dict[str, Any] = {}
        for attr, key in (
            ("has_car", "v2x_has_car"),
            ("has_disclaimer", "v2x_has_disclaimer"),
            ("has_used", "v2x_has_used"),
        ):
            if key in dc_data:
                attrs[attr] = dc_data[key]
        return attrs

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._client.set_v2x_discharge_enabled(True, dc_sn=self._dc_sn)
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._client.set_v2x_discharge_enabled(False, dc_sn=self._dc_sn)
        await self.coordinator.async_request_refresh()
