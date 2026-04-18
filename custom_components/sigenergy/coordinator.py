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


class SigenEnergyCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Polls real-time energy flow every 30 seconds."""

    def __init__(self, hass: HomeAssistant, client: Sigen) -> None:
        super().__init__(
            hass,
            LOGGER,
            name=f"{DOMAIN}_energy",
            update_interval=timedelta(seconds=30),
        )
        self.client = client

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            flow = await self.client.get_energy_flow()
            data: dict[str, Any] = {
                "pv_power": flow.get("pvPower", 0.0),
                "battery_soc": flow.get("batterySoc", 0.0),
                "battery_power": flow.get("batteryPower", 0.0),
                # buySellPower: negative = import from grid, positive = export to grid
                "grid_power": flow.get("buySellPower", 0.0),
                "load_power": flow.get("loadPower", 0.0),
                "ev_power": flow.get("evPower", 0.0),
            }
            if self.client.dc_sn:
                try:
                    data["is_charging"] = await self.client.is_charging()
                except Exception:  # noqa: BLE001
                    data["is_charging"] = None
            return data
        except SigenAuthError as exc:
            raise ConfigEntryAuthFailed(exc) from exc
        except SigenError as exc:
            raise UpdateFailed(exc) from exc
        except Exception as exc:
            raise UpdateFailed(exc) from exc


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
            backup_reserve = await self.client.get_backup_reserve()
            battery_export = await self.client.get_battery_export_limitation()

            return {
                "operational_mode": operational_mode,
                "battery_level": battery_level,
                "export_limit": export_limit,
                "import_limit": import_limit,
                "backup_reserve": backup_reserve,
                "battery_export": battery_export,
            }
        except SigenAuthError as exc:
            raise ConfigEntryAuthFailed(exc) from exc
        except SigenError as exc:
            raise UpdateFailed(exc) from exc
        except Exception as exc:
            raise UpdateFailed(exc) from exc
