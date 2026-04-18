"""DC EV charger endpoints — charging, V2X discharge, scheduling, and history.

Covers the full lifecycle of the DC EV charger (DCEVSE): real-time status,
charge start/stop, charge modes, scheduled charging, and V2X (Vehicle-to-Grid /
Vehicle-to-Home) discharge sessions. Both charging and V2X discharge use the
same physical device and the same DC charger serial number (snCode).

All endpoints take dc_sn (snCode) alongside station_id.

Charging endpoints:
    GET  /device/dcevse/status?stationId={sid}&snCode={dc_sn}
    GET  /device/dcevse/charge/realtime?stationId={sid}&snCode={dc_sn}
    GET  /device/dcevse/discharge/realtime?stationId={sid}&snCode={dc_sn}
    PUT  /device/dcevse/charge/start?enable={0|1}&stationId={sid}&snCode={dc_sn}
    GET  /device/dcevse/charge/mode?stationId={sid}&snCode={dc_sn}
    GET  /device/charge/mode/support?stationId={sid}&snCode={dc_sn}&deviceType=5
    POST /device/charge/check/charge?stationId={sid}   → {"data": bool}
    GET  /device/dcevse/schedule/{stationId}?snCode={dc_sn}
    GET  /device/dcevse/schedule/support/{stationId}?snCode={dc_sn}
    GET  /device/dcevse/auth/mode/{stationId}?snCode={dc_sn}
    GET  /device/dcevse/ocpp/status?stationId={sid}&snCode={dc_sn}
    GET  /device/dcevse/ocpp/condition?stationId={sid}&snCode={dc_sn}
    GET  /data-process/dcevse/energy?stationId={sid}&snCode={dc_sn}
    GET  /data-process/dcevse/record/page?stationId={sid}&snCode={dc_sn}
                                          &current={page}&size={size}
                                          &startTime={YYYYMMDD}&endTime={YYYYMMDD}

V2X endpoints:
    GET  /device/station-v2x/support/v2x?snCode={dc_sn}&stationId={sid}
    GET  /device/station-v2x/select?stationId={sid}&snCode={dc_sn}
    GET  /device/station-v2x/discharge/info?dcSnCode={dc_sn}&stationId={sid}
    POST /device/station-v2x/start/discharge
         body: {"snCode": str, "stationId": int, "duration": int, "powerCap": float|null}
    POST /device/station-v2x/stop/discharge
         body: {"snCode": str, "stationId": int}

Notes:
    - charge/start uses query params, not a JSON body
    - V2X duration is in minutes; powerCap is in kW (null = no cap)
    - stationId is sent as int in V2X POST bodies
    - deviceType=5 identifies the DCEVSE device class
"""

from __future__ import annotations

import logging
from datetime import date

import aiohttp

from .auth import TokenManager

logger = logging.getLogger(__name__)


# ── Status & real-time ────────────────────────────────────────────────────────

async def get_dcevse_status(
    base_url: str, token_mgr: TokenManager, station_id: str, dc_sn: str
) -> dict:
    """Get the overall DC charger status (connected, charging, idle, fault).

    GET {base}/device/dcevse/status?stationId={station_id}&snCode={dc_sn}
    """
    await token_mgr.ensure_valid_token(base_url)
    url = f"{base_url}device/dcevse/status"
    params = {"stationId": station_id, "snCode": dc_sn}
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=token_mgr.headers, params=params) as response:
            return (await response.json())["data"]


async def get_charge_realtime(
    base_url: str, token_mgr: TokenManager, station_id: str, dc_sn: str
) -> dict:
    """Get real-time EV charging data (power, current, voltage, SOC, etc.).

    GET {base}/device/dcevse/charge/realtime?stationId={station_id}&snCode={dc_sn}
    """
    await token_mgr.ensure_valid_token(base_url)
    url = f"{base_url}device/dcevse/charge/realtime"
    params = {"stationId": station_id, "snCode": dc_sn}
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=token_mgr.headers, params=params) as response:
            return (await response.json())["data"]


async def get_discharge_realtime(
    base_url: str, token_mgr: TokenManager, station_id: str, dc_sn: str
) -> dict:
    """Get real-time EV discharge data (during V2X or battery-discharge sessions).

    GET {base}/device/dcevse/discharge/realtime?stationId={station_id}&snCode={dc_sn}
    """
    await token_mgr.ensure_valid_token(base_url)
    url = f"{base_url}device/dcevse/discharge/realtime"
    params = {"stationId": station_id, "snCode": dc_sn}
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=token_mgr.headers, params=params) as response:
            return (await response.json())["data"]


async def is_charging(
    base_url: str, token_mgr: TokenManager, station_id: str
) -> bool:
    """Return True if the EV charger is currently charging.

    POST {base}/device/charge/check/charge?stationId={station_id}
    Response: {"code": 0, "data": false}
    """
    await token_mgr.ensure_valid_token(base_url)
    url = f"{base_url}device/charge/check/charge"
    params = {"stationId": station_id}
    async with aiohttp.ClientSession() as session:
        async with session.post(url, headers=token_mgr.headers, params=params) as response:
            return bool((await response.json())["data"])


# ── Charge control ────────────────────────────────────────────────────────────

async def set_charge_enabled(
    base_url: str,
    token_mgr: TokenManager,
    station_id: str,
    dc_sn: str,
    enabled: bool,
) -> dict:
    """Start (enabled=True) or stop (enabled=False) EV charging.

    PUT {base}/device/dcevse/charge/start?enable={1|0}&stationId={station_id}&snCode={dc_sn}

    Note: control is via query params, not a request body.
    """
    await token_mgr.ensure_valid_token(base_url)
    url = f"{base_url}device/dcevse/charge/start"
    params = {
        "enable": 1 if enabled else 0,
        "stationId": station_id,
        "snCode": dc_sn,
    }
    async with aiohttp.ClientSession() as session:
        async with session.put(url, headers=token_mgr.headers, params=params) as response:
            return await response.json()


# ── Charge mode ───────────────────────────────────────────────────────────────

async def get_charge_mode(
    base_url: str, token_mgr: TokenManager, station_id: str, dc_sn: str
) -> dict:
    """Get the current DC charger charge mode (immediate, scheduled, PV-surplus, etc.).

    GET {base}/device/dcevse/charge/mode?stationId={station_id}&snCode={dc_sn}
    """
    await token_mgr.ensure_valid_token(base_url)
    url = f"{base_url}device/dcevse/charge/mode"
    params = {"stationId": station_id, "snCode": dc_sn}
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=token_mgr.headers, params=params) as response:
            return (await response.json())["data"]


async def get_supported_charge_modes(
    base_url: str, token_mgr: TokenManager, station_id: str, dc_sn: str
) -> dict:
    """Get which charge modes are supported by this charger.

    GET {base}/device/charge/mode/support?stationId={station_id}&snCode={dc_sn}&deviceType=5
    """
    await token_mgr.ensure_valid_token(base_url)
    url = f"{base_url}device/charge/mode/support"
    params = {"stationId": station_id, "snCode": dc_sn, "deviceType": 5}
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=token_mgr.headers, params=params) as response:
            return (await response.json())["data"]


# ── Schedule ──────────────────────────────────────────────────────────────────

async def get_charge_schedule_support(
    base_url: str, token_mgr: TokenManager, station_id: str, dc_sn: str
) -> dict:
    """Check which scheduling features this charger supports.

    GET {base}/device/dcevse/schedule/support/{station_id}?snCode={dc_sn}
    """
    await token_mgr.ensure_valid_token(base_url)
    url = f"{base_url}device/dcevse/schedule/support/{station_id}"
    params = {"snCode": dc_sn}
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=token_mgr.headers, params=params) as response:
            return (await response.json())["data"]


async def get_charge_schedule(
    base_url: str, token_mgr: TokenManager, station_id: str, dc_sn: str
) -> dict:
    """Get the EV charging schedule (time windows for scheduled charging).

    GET {base}/device/dcevse/schedule/{station_id}?snCode={dc_sn}

    TODO: Capture the response shape — likely a list of time windows similar
    to the peak shaving settingList. May warrant a typed dataclass once known.
    """
    await token_mgr.ensure_valid_token(base_url)
    url = f"{base_url}device/dcevse/schedule/{station_id}"
    params = {"snCode": dc_sn}
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=token_mgr.headers, params=params) as response:
            return (await response.json())["data"]


# ── Auth / OCPP ───────────────────────────────────────────────────────────────

async def get_auth_mode(
    base_url: str, token_mgr: TokenManager, station_id: str, dc_sn: str
) -> dict:
    """Get the charger authentication mode (free, RFID, app-controlled, etc.).

    GET {base}/device/dcevse/auth/mode/{station_id}?snCode={dc_sn}
    """
    await token_mgr.ensure_valid_token(base_url)
    url = f"{base_url}device/dcevse/auth/mode/{station_id}"
    params = {"snCode": dc_sn}
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=token_mgr.headers, params=params) as response:
            return (await response.json())["data"]


async def get_ocpp_status(
    base_url: str, token_mgr: TokenManager, station_id: str, dc_sn: str
) -> dict:
    """Get OCPP connection status for this charger.

    GET {base}/device/dcevse/ocpp/status?stationId={station_id}&snCode={dc_sn}
    """
    await token_mgr.ensure_valid_token(base_url)
    url = f"{base_url}device/dcevse/ocpp/status"
    params = {"stationId": station_id, "snCode": dc_sn}
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=token_mgr.headers, params=params) as response:
            return (await response.json())["data"]


# ── Energy & session history ──────────────────────────────────────────────────

async def get_dcevse_energy(
    base_url: str, token_mgr: TokenManager, station_id: str, dc_sn: str
) -> dict:
    """Get cumulative energy statistics for the DC charger.

    GET {base}/data-process/dcevse/energy?stationId={station_id}&snCode={dc_sn}
    """
    await token_mgr.ensure_valid_token(base_url)
    url = f"{base_url}data-process/dcevse/energy"
    params = {"stationId": station_id, "snCode": dc_sn}
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=token_mgr.headers, params=params) as response:
            return (await response.json())["data"]


# ── V2X (Vehicle-to-Grid / Vehicle-to-Home) ───────────────────────────────────

async def get_v2x_support(
    base_url: str, token_mgr: TokenManager, station_id: str, dc_sn: str
) -> dict:
    """Check whether V2X is supported on this DC charger.

    GET {base}/device/station-v2x/support/v2x?snCode={dc_sn}&stationId={station_id}
    """
    await token_mgr.ensure_valid_token(base_url)
    url = f"{base_url}device/station-v2x/support/v2x"
    params = {"snCode": dc_sn, "stationId": station_id}
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=token_mgr.headers, params=params) as response:
            return (await response.json())["data"]


async def get_v2x_vehicles(
    base_url: str, token_mgr: TokenManager, station_id: str, dc_sn: str
) -> dict:
    """Get V2X vehicle selection / paired vehicle info.

    GET {base}/device/station-v2x/select?stationId={station_id}&snCode={dc_sn}
    """
    await token_mgr.ensure_valid_token(base_url)
    url = f"{base_url}device/station-v2x/select"
    params = {"stationId": station_id, "snCode": dc_sn}
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=token_mgr.headers, params=params) as response:
            return (await response.json())["data"]


async def get_v2x_discharge_info(
    base_url: str, token_mgr: TokenManager, station_id: str, dc_sn: str
) -> dict:
    """Get current V2X discharge session status.

    Poll this while a V2X discharge is active to monitor progress.

    GET {base}/device/station-v2x/discharge/info?dcSnCode={dc_sn}&stationId={station_id}
    """
    await token_mgr.ensure_valid_token(base_url)
    url = f"{base_url}device/station-v2x/discharge/info"
    params = {"dcSnCode": dc_sn, "stationId": station_id}
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=token_mgr.headers, params=params) as response:
            return (await response.json())["data"]


async def start_v2x_discharge(
    base_url: str,
    token_mgr: TokenManager,
    station_id: str,
    dc_sn: str,
    duration_minutes: int = 120,
    power_cap_kw: float | None = None,
) -> dict:
    """Start a V2X discharge session (vehicle discharges into home/grid).

    POST {base}/device/station-v2x/start/discharge

    Args:
        duration_minutes: How long to discharge for (default 120 min).
        power_cap_kw:     Maximum discharge power in kW; None = no cap.
    """
    await token_mgr.ensure_valid_token(base_url)
    url = f"{base_url}device/station-v2x/start/discharge"
    payload = {
        "snCode": dc_sn,
        "stationId": int(station_id),
        "duration": duration_minutes,
        "powerCap": power_cap_kw,
    }
    async with aiohttp.ClientSession() as session:
        async with session.post(url, headers=token_mgr.headers, json=payload) as response:
            return await response.json()


async def stop_v2x_discharge(
    base_url: str, token_mgr: TokenManager, station_id: str, dc_sn: str
) -> dict:
    """Stop the current V2X discharge session.

    POST {base}/device/station-v2x/stop/discharge
    """
    await token_mgr.ensure_valid_token(base_url)
    url = f"{base_url}device/station-v2x/stop/discharge"
    payload = {"snCode": dc_sn, "stationId": int(station_id)}
    async with aiohttp.ClientSession() as session:
        async with session.post(url, headers=token_mgr.headers, json=payload) as response:
            return await response.json()


# ── Energy & session history ──────────────────────────────────────────────────

async def get_session_records(
    base_url: str,
    token_mgr: TokenManager,
    station_id: str,
    dc_sn: str,
    start_date: date,
    end_date: date,
    page: int = 1,
    page_size: int = 10,
) -> dict:
    """Get paginated charging session records.

    GET {base}/data-process/dcevse/record/page

    Args:
        start_date: Start of date range.
        end_date:   End of date range.
        page:       Page number (1-based).
        page_size:  Records per page.
    """
    await token_mgr.ensure_valid_token(base_url)
    url = f"{base_url}data-process/dcevse/record/page"
    params = {
        "stationId": station_id,
        "snCode": dc_sn,
        "current": page,
        "size": page_size,
        "startTime": start_date.strftime("%Y%m%d"),
        "endTime": end_date.strftime("%Y%m%d"),
    }
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=token_mgr.headers, params=params) as response:
            return (await response.json())["data"]
