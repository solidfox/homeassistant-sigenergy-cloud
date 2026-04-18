"""Main Sigen client — public interface and orchestration."""

import logging

from .auth import TokenManager, encrypt_password
from .constants import REGION_BASE_URLS
from .energy import get_energy_flow as _get_energy_flow
from .modes import (
    create_dynamic_mode_methods,
    fetch_operational_modes as _fetch_operational_modes,
    get_current_operational_mode,
    set_operational_mode as _set_operational_mode,
)
from .smart_loads import (
    fetch_smart_load_details,
    fetch_smart_load_list,
    get_smart_loads_with_consumption,
    set_smart_load_state as _set_smart_load_state,
)
from .station import fetch_station_info as _fetch_station_info
from .peak_shaving import (
    PeakShavingSlot,
    PeakShavingSchedule,
    get_peak_shaving_schedule as _get_peak_shaving_schedule,
    set_peak_shaving_slot as _set_peak_shaving_slot,
    set_peak_shaving_schedule as _set_peak_shaving_schedule,
)
from .power_limits import (
    get_export_limit as _get_export_limit,
    set_export_limit as _set_export_limit,
    get_import_limit as _get_import_limit,
    set_import_limit as _set_import_limit,
    get_battery_export_limitation as _get_battery_export_limitation,
    set_battery_export_limitation as _set_battery_export_limitation,
)
from .dc_charger import (
    get_dcevse_status as _get_dcevse_status,
    get_charge_realtime as _get_charge_realtime,
    get_discharge_realtime as _get_discharge_realtime,
    is_charging as _is_charging,
    set_charge_enabled as _set_charge_enabled,
    get_charge_mode as _get_charge_mode,
    get_supported_charge_modes as _get_supported_charge_modes,
    get_charge_schedule as _get_charge_schedule,
    get_charge_schedule_support as _get_charge_schedule_support,
    get_auth_mode as _get_auth_mode,
    get_ocpp_status as _get_ocpp_status,
    get_dcevse_energy as _get_dcevse_energy,
    get_session_records as _get_session_records,
    get_v2x_support as _get_v2x_support,
    get_v2x_vehicles as _get_v2x_vehicles,
    get_v2x_discharge_info as _get_v2x_discharge_info,
    start_v2x_discharge as _start_v2x_discharge,
    stop_v2x_discharge as _stop_v2x_discharge,
)
from .tariff import (
    DirectionCostSettings,
    get_latest_price as _get_latest_price,
    get_static_price as _get_static_price,
    get_country_currency as _get_country_currency,
    get_tariff_detail as _get_tariff_detail,
    get_price_cost as _get_price_cost,
    save_direction_cost as _save_direction_cost,
    get_tariff_soc_history as _get_tariff_soc_history,
)
from .battery_level import (
    BatteryLevelSettings,
    get_battery_level_settings as _get_battery_level_settings,
    set_battery_level_settings as _set_battery_level_settings,
    get_backup_reserve as _get_backup_reserve,
    set_backup_reserve as _set_backup_reserve,
)

logger = logging.getLogger(__name__)


class Sigen:
    """Async client for the Sigenergy cloud API.

    Usage::

        api = Sigen("user@example.com", "password", region="eu")
        await api.async_initialize()
        flow = await api.get_energy_flow()
    """

    def __init__(self, username: str, password: str, region: str = "eu"):
        if region not in REGION_BASE_URLS:
            raise ValueError(
                f"Unsupported region '{region}'. "
                f"Supported regions: {', '.join(REGION_BASE_URLS)}"
            )

        self.username = username
        self._raw_password = password
        self.password = encrypt_password(password)
        self.base_url = REGION_BASE_URLS[region]

        self._token_mgr = TokenManager()
        self._nb_client = None  # NorthboundClient, initialized on demand

        # Populated by async_initialize / fetch_station_info
        self.station_id: str | None = None
        self.ac_sn: str | None = None
        self.dc_sn: str | None = None

        # Populated lazily
        self.operational_modes: dict | None = None
        self.smart_loads: list = []
        self.smart_load_id_map: dict[int, int] = {}

    async def async_initialize(self) -> None:
        """Full init: authenticate → station info → smart load IDs → dynamic methods."""
        await self._token_mgr.get_access_token(self.base_url, self.username, self.password)
        await self.fetch_station_info()
        await self._fetch_smart_load_ids()
        await self._create_dynamic_methods()

    # ── Station ──────────────────────────────────────────────────────────

    async def fetch_station_info(self) -> dict:
        """Fetch station info and populate station_id, ac_sn, dc_sn."""
        data = await _fetch_station_info(self.base_url, self._token_mgr)
        self.station_id = data["stationId"]

        if data.get("hasAcCharger"):
            self.ac_sn = data["acSnList"][0] if data.get("acSnList") else None

        self.dc_sn = data["dcSnList"][0] if data.get("dcSnList") else None
        return data

    # ── Energy ───────────────────────────────────────────────────────────

    async def get_energy_flow(self) -> dict:
        """Return real-time energy flow data."""
        await self._token_mgr.ensure_valid_token(self.base_url)
        return await _get_energy_flow(self.base_url, self._token_mgr, self.station_id)

    # ── Operational modes ────────────────────────────────────────────────

    async def get_operational_modes(self) -> dict:
        """Return all operational modes (lazy-fetches on first call)."""
        if not self.operational_modes:
            await self.fetch_operational_modes()
        return self.operational_modes

    async def fetch_operational_modes(self) -> dict:
        """Fetch operational modes from the API and cache them."""
        self.operational_modes = await _fetch_operational_modes(
            self.base_url, self._token_mgr, self.station_id
        )
        return self.operational_modes

    async def get_operational_mode(self) -> str:
        """Return the label/name of the current operational mode."""
        if self.operational_modes is None:
            await self.get_operational_modes()
        return await get_current_operational_mode(
            self.base_url, self._token_mgr, self.station_id, self.operational_modes
        )

    async def set_operational_mode(self, mode: int, profile_id: int = -1) -> dict:
        """Set the station's operational mode."""
        return await _set_operational_mode(
            self.base_url, self._token_mgr, self.station_id, mode, profile_id
        )

    # ── Northbound API ────────────────────────────────────────────────────

    async def init_northbound(self) -> None:
        """Initialize northbound API client and authenticate."""
        from .northbound import NorthboundClient
        self._nb_client = NorthboundClient(
            self.base_url, self.username, self._raw_password
        )
        await self._nb_client.login()
        logger.info("Northbound API authenticated")

    async def nb_query_mode(self) -> int:
        """Query current operating mode via northbound API."""
        if not self._nb_client:
            raise RuntimeError(
                "Northbound client not initialized. Call init_northbound() first."
            )
        return await self._nb_client.query_mode(self.station_id)

    async def nb_switch_mode(self, mode: int) -> dict:
        """Switch operating mode via northbound API."""
        if not self._nb_client:
            raise RuntimeError(
                "Northbound client not initialized. Call init_northbound() first."
            )
        return await self._nb_client.switch_mode(self.station_id, mode)

    # ── Smart loads ──────────────────────────────────────────────────────

    async def get_smart_loads(self) -> list:
        """Return smart loads enriched with consumption stats."""
        self.smart_loads, self.smart_load_id_map = await get_smart_loads_with_consumption(
            self.base_url, self._token_mgr, self.station_id, self.smart_load_id_map
        )
        return self.smart_loads

    async def set_smart_load_state(self, load_path: int, state: int) -> dict:
        """Turn a smart load on (1) or off (0)."""
        return await _set_smart_load_state(
            self.base_url, self._token_mgr, self.station_id, load_path, state
        )

    # ── Peak shaving ─────────────────────────────────────────────────────

    async def get_peak_shaving_schedule(self) -> PeakShavingSchedule:
        """Fetch the full peak shaving schedule."""
        return await _get_peak_shaving_schedule(self.base_url, self._token_mgr, self.station_id)

    async def set_peak_shaving_slot(self, slot: PeakShavingSlot) -> dict:
        """Update a single slot (read-modify-write under the hood)."""
        return await _set_peak_shaving_slot(
            self.base_url, self._token_mgr, self.station_id, slot
        )

    async def set_peak_shaving_schedule(self, schedule: PeakShavingSchedule) -> dict:
        """Replace the entire peak shaving schedule."""
        return await _set_peak_shaving_schedule(
            self.base_url, self._token_mgr, self.station_id, schedule
        )

    # ── Power limits ─────────────────────────────────────────────────────

    async def get_export_limit(self) -> dict:
        """Get current grid export power limit settings."""
        return await _get_export_limit(self.base_url, self._token_mgr, self.station_id)

    async def set_export_limit(self, limit_kw: float, enabled: bool = True) -> dict:
        """Set the grid export power limit in kW."""
        return await _set_export_limit(
            self.base_url, self._token_mgr, self.station_id, limit_kw, enabled
        )

    async def get_import_limit(self) -> dict:
        """Get current grid import power limit settings."""
        return await _get_import_limit(self.base_url, self._token_mgr, self.station_id)

    async def set_import_limit(self, limit_kw: float, enabled: bool = True) -> dict:
        """Set the grid import power limit in kW."""
        return await _set_import_limit(
            self.base_url, self._token_mgr, self.station_id, limit_kw, enabled
        )

    async def get_battery_export_limitation(self) -> dict:
        """Get whether battery-to-grid export is enabled."""
        return await _get_battery_export_limitation(
            self.base_url, self._token_mgr, self.station_id
        )

    async def set_battery_export_limitation(self, enabled: bool) -> dict:
        """Enable or disable battery export to grid."""
        return await _set_battery_export_limitation(
            self.base_url, self._token_mgr, self.station_id, enabled
        )

    # ── Battery SOC levels ───────────────────────────────────────────────

    async def get_battery_level_settings(self) -> BatteryLevelSettings:
        """Fetch battery charge/discharge/peak-shaving/backup SOC limits."""
        return await _get_battery_level_settings(
            self.base_url, self._token_mgr, self.station_id
        )

    async def set_battery_level_settings(self, settings: BatteryLevelSettings) -> dict:
        """Update battery SOC level settings (all four limits written together)."""
        return await _set_battery_level_settings(
            self.base_url, self._token_mgr, self.station_id, settings
        )

    async def get_backup_reserve(self) -> int:
        """Get the backup reserve SOC percentage."""
        return await _get_backup_reserve(self.base_url, self._token_mgr, self.station_id)

    async def set_backup_reserve(self, reserve_pct: int) -> dict:
        """Set the backup reserve SOC percentage."""
        return await _set_backup_reserve(
            self.base_url, self._token_mgr, self.station_id, reserve_pct
        )

    # ── V2X / DC EV charger ──────────────────────────────────────────────

    async def get_v2x_support(self) -> dict:
        """Check whether V2X is supported on this DC charger."""
        return await _get_v2x_support(
            self.base_url, self._token_mgr, self.station_id, self.dc_sn
        )

    async def get_v2x_vehicles(self) -> dict:
        """Get V2X paired vehicle info."""
        return await _get_v2x_vehicles(
            self.base_url, self._token_mgr, self.station_id, self.dc_sn
        )

    async def get_v2x_discharge_info(self) -> dict:
        """Get current V2X discharge session status."""
        return await _get_v2x_discharge_info(
            self.base_url, self._token_mgr, self.station_id, self.dc_sn
        )

    async def start_v2x_discharge(
        self,
        duration_minutes: int = 120,
        power_cap_kw: float | None = None,
    ) -> dict:
        """Start a V2X discharge session.

        Args:
            duration_minutes: How long to discharge for (default 120 min).
            power_cap_kw:     Max discharge power in kW; None = no cap.
        """
        return await _start_v2x_discharge(
            self.base_url, self._token_mgr, self.station_id, self.dc_sn,
            duration_minutes, power_cap_kw,
        )

    async def stop_v2x_discharge(self) -> dict:
        """Stop the current V2X discharge session."""
        return await _stop_v2x_discharge(
            self.base_url, self._token_mgr, self.station_id, self.dc_sn
        )

    # ── DC EV charger ─────────────────────────────────────────────────────

    async def get_dcevse_status(self) -> dict:
        """Get overall DC charger status (connected, charging, idle, fault)."""
        return await _get_dcevse_status(
            self.base_url, self._token_mgr, self.station_id, self.dc_sn
        )

    async def get_charge_realtime(self) -> dict:
        """Get real-time EV charging data (power, current, voltage, SOC)."""
        return await _get_charge_realtime(
            self.base_url, self._token_mgr, self.station_id, self.dc_sn
        )

    async def get_discharge_realtime(self) -> dict:
        """Get real-time EV discharge data (during V2X or discharge sessions)."""
        return await _get_discharge_realtime(
            self.base_url, self._token_mgr, self.station_id, self.dc_sn
        )

    async def is_charging(self) -> bool:
        """Return True if the EV charger is currently active."""
        return await _is_charging(self.base_url, self._token_mgr, self.station_id)

    async def set_charge_enabled(self, enabled: bool) -> dict:
        """Start (True) or stop (False) EV charging."""
        return await _set_charge_enabled(
            self.base_url, self._token_mgr, self.station_id, self.dc_sn, enabled
        )

    async def get_charge_mode(self) -> dict:
        """Get current charge mode (immediate, scheduled, PV-surplus, etc.)."""
        return await _get_charge_mode(
            self.base_url, self._token_mgr, self.station_id, self.dc_sn
        )

    async def get_supported_charge_modes(self) -> dict:
        """Get which charge modes this charger supports."""
        return await _get_supported_charge_modes(
            self.base_url, self._token_mgr, self.station_id, self.dc_sn
        )

    async def get_charge_schedule(self) -> dict:
        """Get the EV charging schedule (time windows for scheduled charging)."""
        return await _get_charge_schedule(
            self.base_url, self._token_mgr, self.station_id, self.dc_sn
        )

    async def get_charge_schedule_support(self) -> dict:
        """Check which scheduling features this charger supports."""
        return await _get_charge_schedule_support(
            self.base_url, self._token_mgr, self.station_id, self.dc_sn
        )

    async def get_auth_mode(self) -> dict:
        """Get charger authentication mode (free, RFID, app-controlled, etc.)."""
        return await _get_auth_mode(
            self.base_url, self._token_mgr, self.station_id, self.dc_sn
        )

    async def get_ocpp_status(self) -> dict:
        """Get OCPP connection status for this charger."""
        return await _get_ocpp_status(
            self.base_url, self._token_mgr, self.station_id, self.dc_sn
        )

    async def get_dcevse_energy(self) -> dict:
        """Get cumulative energy statistics for the DC charger."""
        return await _get_dcevse_energy(
            self.base_url, self._token_mgr, self.station_id, self.dc_sn
        )

    async def get_session_records(
        self,
        start_date,
        end_date,
        page: int = 1,
        page_size: int = 10,
    ) -> dict:
        """Get paginated charging session history."""
        return await _get_session_records(
            self.base_url, self._token_mgr, self.station_id, self.dc_sn,
            start_date, end_date, page, page_size,
        )

    # ── Tariff & pricing ─────────────────────────────────────────────────

    async def get_latest_price(self) -> dict:
        """Get current electricity price settings (static/manual)."""
        return await _get_latest_price(self.base_url, self._token_mgr, self.station_id)

    async def get_static_price(self) -> dict:
        """Get the static electricity price configuration."""
        return await _get_static_price(self.base_url, self._token_mgr, self.station_id)

    async def get_country_currency(self) -> dict:
        """Get the country and currency configured for this station."""
        return await _get_country_currency(self.base_url, self._token_mgr, self.station_id)

    async def get_tariff_detail(self) -> dict:
        """Get the full tariff configuration used by AI mode (TOU, buy/sell prices)."""
        return await _get_tariff_detail(self.base_url, self._token_mgr, self.station_id)

    async def get_price_cost(self) -> dict:
        """Get the current direction cost / price-cost settings for AI mode."""
        return await _get_price_cost(self.base_url, self._token_mgr, self.station_id)

    async def save_direction_cost(self, settings: DirectionCostSettings) -> dict:
        """Save buy/sell price config for AI-mode optimisation (taxes, fees, coefficients)."""
        return await _save_direction_cost(
            self.base_url, self._token_mgr, self.station_id, settings
        )

    async def get_tariff_soc_history(self, day, include_prediction: bool = False) -> dict:
        """Get a day's tariff and SOC time-series (5-min intervals, read-only)."""
        return await _get_tariff_soc_history(
            self.base_url, self._token_mgr, self.station_id, day, include_prediction
        )

    # ── Internal helpers ─────────────────────────────────────────────────

    async def _fetch_smart_load_ids(self) -> None:
        """Build the load_path → smartLoadId cache."""
        await self._token_mgr.ensure_valid_token(self.base_url)
        loads = await fetch_smart_load_list(self.base_url, self._token_mgr, self.station_id)

        for load in loads:
            if "path" not in load:
                continue
            load_path = load["path"]
            load_name = load.get("name", f"Load {load_path}")
            try:
                details = await fetch_smart_load_details(
                    self.base_url, self._token_mgr, self.station_id, load_path
                )
                if details:
                    smart_load_id = details.get("smartLoadId")
                    if smart_load_id is not None:
                        self.smart_load_id_map[load_path] = smart_load_id
                        logger.debug(
                            "Cached smartLoadId %s for load %s (path: %s)",
                            smart_load_id, load_name, load_path,
                        )
            except Exception as e:
                logger.error("Error fetching smartLoadId for load %s: %s", load_name, e)

        logger.info("Cached %d smart load IDs", len(self.smart_load_id_map))

    async def _create_dynamic_methods(self) -> None:
        """Create set_operational_mode_* and enable/disable_smart_load_* methods."""
        # Mode methods
        await self.get_operational_modes()
        created = create_dynamic_mode_methods(Sigen, self.operational_modes)
        logger.debug("Created dynamic mode methods: %s", created)

        # Smart load methods
        await self.get_smart_loads()
        if self.smart_loads:
            for load in self.smart_loads:
                if "path" not in load or "name" not in load:
                    continue
                safe_name = load["name"].lower().replace(" ", "_").replace("-", "_")
                load_path = load["path"]

                # enable
                enable_name = f"enable_smart_load_{safe_name}"

                def _make_enable(path):
                    async def _method(self):
                        return await self.set_smart_load_state(path, 1)
                    _method.__name__ = enable_name
                    return _method

                setattr(Sigen, enable_name, _make_enable(load_path))

                # disable
                disable_name = f"disable_smart_load_{safe_name}"

                def _make_disable(path):
                    async def _method(self):
                        return await self.set_smart_load_state(path, 0)
                    _method.__name__ = disable_name
                    return _method

                setattr(Sigen, disable_name, _make_disable(load_path))
