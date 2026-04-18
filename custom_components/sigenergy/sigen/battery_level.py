"""Battery SOC level limit endpoints.

Controls the SOC thresholds that govern charge/discharge behaviour.
All four limits are written together in a single PUT call.

Endpoints:
    GET /device/energy-profile/battery/level/{stationId}
    PUT /device/energy-profile/battery/level
        body: {
            "stationId": int,
            "chargeSOC":      "99",   # max charge target (%)
            "dischargeSOC":   "1",    # min discharge floor (%)
            "peakShavingSOC": "11",   # min SOC during peak shaving (%)
            "backupSOC":      "4",    # reserved backup capacity (%)
        }
        (all SOC values are strings on the wire)

Also exposes backup reserve (a related but separate endpoint):
    GET /device/setting/backup/reserve/{stationId}
    PUT /device/setting/backup/reserve
        body: {"stationId": int, "backupReserve": int}
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import aiohttp

from .auth import TokenManager

logger = logging.getLogger(__name__)


@dataclass
class BatteryLevelSettings:
    """SOC thresholds for charge/discharge/peak-shaving/backup.

    All values are percentages (0–100).

    Attributes:
        charge_soc:       Target SOC for charging (upper limit).
        discharge_soc:    Minimum SOC before stopping discharge.
        peak_shaving_soc: Minimum SOC during peak shaving (battery will not
                          discharge below this level to serve peak shaving).
        backup_soc:       SOC reserved for backup power (grid outage).
    """

    charge_soc: int
    discharge_soc: int
    peak_shaving_soc: int
    backup_soc: int

    @classmethod
    def from_api(cls, data: dict) -> "BatteryLevelSettings":
        return cls(
            charge_soc=int(float(data["chargeSOC"])),
            discharge_soc=int(float(data["dischargeSOC"])),
            peak_shaving_soc=int(float(data["peakShavingSOC"])),
            backup_soc=int(float(data["backupSOC"])),
        )

    def to_api(self, station_id: int) -> dict:
        return {
            "stationId": station_id,
            "chargeSOC": str(self.charge_soc),
            "dischargeSOC": str(self.discharge_soc),
            "peakShavingSOC": str(self.peak_shaving_soc),
            "backupSOC": str(self.backup_soc),
        }


async def get_battery_level_settings(
    base_url: str, token_mgr: TokenManager, station_id: str
) -> BatteryLevelSettings:
    """Fetch battery SOC level settings.

    GET {base}/device/energy-profile/battery/level/{station_id}
    """
    await token_mgr.ensure_valid_token(base_url)
    url = f"{base_url}device/energy-profile/battery/level/{station_id}"
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=token_mgr.headers) as response:
            data = (await response.json())["data"]
            return BatteryLevelSettings.from_api(data)


async def set_battery_level_settings(
    base_url: str,
    token_mgr: TokenManager,
    station_id: str,
    settings: BatteryLevelSettings,
) -> dict:
    """Update battery SOC level settings.

    All four SOC limits must be provided — read first if you only want
    to change one value.

    PUT {base}/device/energy-profile/battery/level
    """
    await token_mgr.ensure_valid_token(base_url)
    url = f"{base_url}device/energy-profile/battery/level"
    async with aiohttp.ClientSession() as session:
        async with session.put(
            url, headers=token_mgr.headers, json=settings.to_api(int(station_id))
        ) as response:
            return await response.json()


async def get_backup_reserve(
    base_url: str, token_mgr: TokenManager, station_id: str
) -> int:
    """Get the backup reserve SOC percentage.

    GET {base}/device/setting/backup/reserve/{station_id}
    """
    await token_mgr.ensure_valid_token(base_url)
    url = f"{base_url}device/setting/backup/reserve/{station_id}"
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=token_mgr.headers) as response:
            data = (await response.json())["data"]
            return int(data["backupReserve"])


async def set_backup_reserve(
    base_url: str, token_mgr: TokenManager, station_id: str, reserve_pct: int
) -> dict:
    """Set the backup reserve SOC percentage.

    PUT {base}/device/setting/backup/reserve

    Args:
        reserve_pct: SOC % to keep reserved for backup (e.g. 3).
    """
    await token_mgr.ensure_valid_token(base_url)
    url = f"{base_url}device/setting/backup/reserve"
    payload = {"stationId": int(station_id), "backupReserve": reserve_pct}
    async with aiohttp.ClientSession() as session:
        async with session.put(url, headers=token_mgr.headers, json=payload) as response:
            return await response.json()
