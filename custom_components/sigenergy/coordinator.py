"""DataUpdateCoordinators for Sigenergy."""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING, Any

from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DOMAIN, LOGGER
from .sigen.exceptions import SigenAuthError, SigenError

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from .sigen import Sigen


def _v2x_is_active(info: dict | None) -> bool:
    """Return True if a V2X discharge session is currently active.

    The API returns {'disChargePower': -3.108, 'carSOC': 30.0,
    'evdcCutoutEnableTime': <unix_ts>, 'delayCutout': 1} when active,
    and an empty dict or zero/null values when idle.
    """
    if not info:
        return False
    # disChargePower is non-zero (negative) during active discharge
    discharge_power = info.get("disChargePower")
    if discharge_power:
        return True
    # Fallback: a future cutout timestamp also indicates an active session
    import time  # noqa: PLC0415
    cutout = info.get("evdcCutoutEnableTime")
    return bool(cutout and cutout > time.time())


class SigenSettingsCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Polls device settings every 5 minutes."""

    def __init__(self, hass: HomeAssistant, client: Sigen) -> None:
        super().__init__(
            hass,
            LOGGER,
            name=f"{DOMAIN}_settings",
            update_interval=timedelta(minutes=5),
        )
        self.client = client
        # Maps mode label → (mode_int, profile_id); -1 = no custom profile
        self.available_modes: dict[str, tuple[int, int]] = {}
        # Persists V2X power cap across setting refreshes; set by the number entity
        self.v2x_power_cap_kw: float | None = None

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            if not self.available_modes:
                modes_data = await self.client.fetch_operational_modes()
                for m in modes_data.get("defaultWorkingModes", []):
                    self.available_modes[m["label"]] = (int(m["value"]), -1)
                for m in modes_data.get("energyProfileItems", []):
                    self.available_modes[m["name"]] = (9, m["profileId"])

            operational_mode = await self.client.get_operational_mode()
            battery_level = await self.client.get_battery_level_settings()
            export_limit = await self.client.get_export_limit()
            import_limit = await self.client.get_import_limit()
            battery_export = await self.client.get_battery_export_limitation()
            peak_shaving = await self.client.get_peak_shaving_schedule()

            return {
                "operational_mode": operational_mode,
                "battery_level": battery_level,
                "export_limit": export_limit,
                "import_limit": import_limit,
                "battery_export": battery_export,
                "peak_shaving": peak_shaving,
            }
        except SigenAuthError as exc:
            raise ConfigEntryAuthFailed(exc) from exc
        except SigenError as exc:
            raise UpdateFailed(exc) from exc
        except Exception as exc:
            raise UpdateFailed(exc) from exc


class SigenStatusCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Polls real-time device status every 30 seconds.

    Covers EV charge power (from energy flow), charging active state,
    and V2X discharge active state. Only calls the DC-charger endpoints
    when a DC charger SN is available.
    """

    def __init__(self, hass: HomeAssistant, client: Sigen) -> None:
        super().__init__(
            hass,
            LOGGER,
            name=f"{DOMAIN}_status",
            update_interval=timedelta(seconds=30),
        )
        self.client = client

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            flow = await self.client.get_energy_flow()
            data: dict[str, Any] = {
                "ev_power": flow.get("evPower", 0.0),
            }

            if self.client.dc_sn:
                try:
                    data["is_charging"] = await self.client.is_charging()
                except Exception:  # noqa: BLE001
                    data["is_charging"] = None

                try:
                    info = await self.client.get_v2x_discharge_info()
                    data["v2x_active"] = _v2x_is_active(info)
                except Exception:  # noqa: BLE001
                    data["v2x_active"] = None

            return data
        except SigenAuthError as exc:
            raise ConfigEntryAuthFailed(exc) from exc
        except SigenError as exc:
            raise UpdateFailed(exc) from exc
        except Exception as exc:
            raise UpdateFailed(exc) from exc
