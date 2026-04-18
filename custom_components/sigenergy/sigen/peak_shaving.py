"""Peak shaving schedule endpoints.

Peak shaving is schedule-based: you define time-window slots, each with a
grid demand target (peakPower). The battery discharges when grid import
exceeds the target during an active slot.

API always reads/writes the FULL schedule. There is no per-slot endpoint,
so updating one slot requires a read-modify-write.

Endpoints (stationId = plant-level SN, e.g. 12025061000219):
    GET  /device/dischargesetting/peak/shaving/{stationId}
    POST /device/dischargesetting/peak/shaving

POST body shape:
    {
        "stationId": 12025061000219,
        "controlMode": 1,          # 1 = enabled, 0 = disabled
        "shavingSOC": 10,          # minimum battery SOC % before stopping discharge
        "settingList": [
            {
                "whichDay": "1,2,3,4,5,6,7",  # comma-separated 1=Mon…7=Sun (all days)
                "startTime": "00:00",
                "endTime":   "06:00",
                "peakPower": 9                 # kW — max allowed grid import
            },
            ...
        ]
    }
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import aiohttp

from .auth import TokenManager

logger = logging.getLogger(__name__)


@dataclass
class PeakShavingSlot:
    """One time-window entry in the peak shaving schedule.

    Attributes:
        index:         0-based position in the settingList.
        which_days:    List of day-of-week integers (1=Mon … 7=Sun).
                       Typically [1,2,3,4,5,6,7] for every day.
        start_time:    Window start in "HH:MM" 24-hour format.
        end_time:      Window end   in "HH:MM" 24-hour format ("24:00" is valid).
        peak_power_kw: Maximum allowed grid import in kW for this window.
                       Battery discharges to keep grid draw at or below this.
    """

    index: int
    which_days: list[int]
    start_time: str
    end_time: str
    peak_power_kw: float

    @classmethod
    def from_api(cls, index: int, data: dict) -> "PeakShavingSlot":
        """Construct from a single entry in the API settingList."""
        return cls(
            index=index,
            which_days=[int(d) for d in data["whichDay"].split(",")],
            start_time=data["startTime"],
            end_time=data["endTime"],
            peak_power_kw=float(data["peakPower"]),
        )

    def to_api(self) -> dict:
        """Serialise to the shape expected in settingList."""
        return {
            "whichDay": ",".join(str(d) for d in self.which_days),
            "startTime": self.start_time,
            "endTime": self.end_time,
            "peakPower": self.peak_power_kw,
        }


@dataclass
class PeakShavingSchedule:
    """Full peak shaving configuration for a station.

    Attributes:
        enabled:      Whether peak shaving is active (controlMode 1/0).
        shaving_soc:  Minimum battery SOC % — discharge stops below this level.
        slots:        Ordered list of time-window slots.
    """

    enabled: bool
    shaving_soc: int
    slots: list[PeakShavingSlot] = field(default_factory=list)

    @classmethod
    def from_api(cls, data: dict) -> "PeakShavingSchedule":
        """Construct from the full API GET response data dict."""
        slots = [
            PeakShavingSlot.from_api(i, entry)
            for i, entry in enumerate(data.get("settingList", []))
        ]
        return cls(
            enabled=data.get("controlMode", 0) == 1,
            shaving_soc=int(data.get("shavingSOC", 0)),
            slots=slots,
        )

    def to_api(self, station_id: int) -> dict:
        """Serialise to the full POST body."""
        return {
            "stationId": station_id,
            "controlMode": 1 if self.enabled else 0,
            "shavingSOC": self.shaving_soc,
            "settingList": [s.to_api() for s in self.slots],
        }


async def get_peak_shaving_schedule(
    base_url: str, token_mgr: TokenManager, station_id: str
) -> PeakShavingSchedule:
    """Fetch the full peak shaving schedule for a station.

    GET {base}/device/dischargesetting/peak/shaving/{station_id}
    """
    await token_mgr.ensure_valid_token(base_url)
    url = f"{base_url}device/dischargesetting/peak/shaving/{station_id}"
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=token_mgr.headers) as response:
            data = (await response.json())["data"]
            return PeakShavingSchedule.from_api(data)


async def set_peak_shaving_schedule(
    base_url: str,
    token_mgr: TokenManager,
    station_id: str,
    schedule: PeakShavingSchedule,
) -> dict:
    """Replace the entire peak shaving schedule.

    POST {base}/device/dischargesetting/peak/shaving

    The API only accepts the full schedule — there is no per-slot endpoint.
    To update a single slot, fetch the schedule first, mutate the desired
    slot, then call this function.
    """
    await token_mgr.ensure_valid_token(base_url)
    url = f"{base_url}device/dischargesetting/peak/shaving"
    payload = schedule.to_api(int(station_id))
    async with aiohttp.ClientSession() as session:
        async with session.post(url, headers=token_mgr.headers, json=payload) as response:
            return await response.json()


async def set_peak_shaving_slot(
    base_url: str,
    token_mgr: TokenManager,
    station_id: str,
    slot: PeakShavingSlot,
) -> dict:
    """Update a single slot via read-modify-write.

    Fetches the current schedule, replaces the slot at slot.index,
    and writes the full schedule back.
    """
    schedule = await get_peak_shaving_schedule(base_url, token_mgr, station_id)
    if slot.index >= len(schedule.slots):
        raise ValueError(
            f"Slot index {slot.index} out of range "
            f"(schedule has {len(schedule.slots)} slots)"
        )
    schedule.slots[slot.index] = slot
    return await set_peak_shaving_schedule(base_url, token_mgr, station_id, schedule)
