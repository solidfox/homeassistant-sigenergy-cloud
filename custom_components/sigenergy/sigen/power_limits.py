"""Grid import/export power limit endpoints.

These are separate owner-settable limits on how much power can flow
in or out of the grid. Values are in kW as strings on the wire.

Endpoints (stationId = plant-level SN):
    GET /device/energy-profile/grid/limitation/export/{stationId}
    PUT /device/energy-profile/grid/limitation/export
        body: {"stationId": int, "enable": bool,
               "maxLimitationOwner": "17.000", "maxLimitationInstaller": null}

    GET /device/energy-profile/grid/limitation/import/{stationId}
    PUT /device/energy-profile/grid/limitation/import
        body: {"stationId": int, "enable": bool,
               "maxLimitationOwner": "5", "maxLimitationInstaller": null}

There is also a battery-level export limitation (separate concept — prevents
the battery from exporting to the grid at all):
    GET /device/energy-profile/battery/export/limitation/{stationId}
    PUT /device/energy-profile/battery/export/limitation
        body: {"stationId": int, "installerSetEnable": null, "ownerSetEnable": bool}
"""

from __future__ import annotations

import logging

import aiohttp

from .auth import TokenManager

logger = logging.getLogger(__name__)


async def get_export_limit(
    base_url: str, token_mgr: TokenManager, station_id: str
) -> dict:
    """Get current grid export power limit settings.

    GET {base}/device/energy-profile/grid/limitation/export/{station_id}
    """
    await token_mgr.ensure_valid_token(base_url)
    url = f"{base_url}device/energy-profile/grid/limitation/export/{station_id}"
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=token_mgr.headers) as response:
            return (await response.json())["data"]


async def set_export_limit(
    base_url: str,
    token_mgr: TokenManager,
    station_id: str,
    limit_kw: float,
    enabled: bool = True,
) -> dict:
    """Set the grid export power limit.

    PUT {base}/device/energy-profile/grid/limitation/export

    Args:
        limit_kw: Maximum export power in kW (0 = no export allowed).
        enabled:  Whether the limit is active.
    """
    await token_mgr.ensure_valid_token(base_url)
    url = f"{base_url}device/energy-profile/grid/limitation/export"
    payload = {
        "stationId": int(station_id),
        "enable": enabled,
        "maxLimitationOwner": f"{limit_kw:.3f}",
        "maxLimitationInstaller": None,
    }
    async with aiohttp.ClientSession() as session:
        async with session.put(url, headers=token_mgr.headers, json=payload) as response:
            return await response.json()


async def get_import_limit(
    base_url: str, token_mgr: TokenManager, station_id: str
) -> dict:
    """Get current grid import power limit settings.

    GET {base}/device/energy-profile/grid/limitation/import/{station_id}
    """
    await token_mgr.ensure_valid_token(base_url)
    url = f"{base_url}device/energy-profile/grid/limitation/import/{station_id}"
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=token_mgr.headers) as response:
            return (await response.json())["data"]


async def set_import_limit(
    base_url: str,
    token_mgr: TokenManager,
    station_id: str,
    limit_kw: float,
    enabled: bool = True,
) -> dict:
    """Set the grid import power limit.

    PUT {base}/device/energy-profile/grid/limitation/import

    Args:
        limit_kw: Maximum import power in kW.
        enabled:  Whether the limit is active.
    """
    await token_mgr.ensure_valid_token(base_url)
    url = f"{base_url}device/energy-profile/grid/limitation/import"
    payload = {
        "stationId": int(station_id),
        "enable": enabled,
        "maxLimitationOwner": f"{limit_kw:.3f}",
        "maxLimitationInstaller": None,
    }
    async with aiohttp.ClientSession() as session:
        async with session.put(url, headers=token_mgr.headers, json=payload) as response:
            return await response.json()


async def get_battery_export_limitation(
    base_url: str, token_mgr: TokenManager, station_id: str
) -> dict:
    """Get whether battery-to-grid export is enabled.

    This is distinct from the grid export limit above — it's a simple
    on/off switch controlling whether the battery can export to the grid
    at all (e.g. for feed-in tariff or grid regulation compliance).

    GET {base}/device/energy-profile/battery/export/limitation/{station_id}
    """
    await token_mgr.ensure_valid_token(base_url)
    url = f"{base_url}device/energy-profile/battery/export/limitation/{station_id}"
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=token_mgr.headers) as response:
            return (await response.json())["data"]


async def set_battery_export_limitation(
    base_url: str,
    token_mgr: TokenManager,
    station_id: str,
    enabled: bool,
) -> dict:
    """Enable or disable battery export to the grid.

    PUT {base}/device/energy-profile/battery/export/limitation

    Args:
        enabled: True = battery may export to grid; False = battery cannot.
    """
    await token_mgr.ensure_valid_token(base_url)
    url = f"{base_url}device/energy-profile/battery/export/limitation"
    payload = {
        "stationId": int(station_id),
        "installerSetEnable": None,
        "ownerSetEnable": enabled,
    }
    async with aiohttp.ClientSession() as session:
        async with session.put(url, headers=token_mgr.headers, json=payload) as response:
            return await response.json()
