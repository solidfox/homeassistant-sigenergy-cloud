"""DataUpdateCoordinators for Sigenergy."""

from __future__ import annotations

import time
from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING, Any

from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from sigenergy_cloud import SigenergyCloudAuthError, SigenergyCloudError

from .const import DOMAIN, LOGGER

_STATUS_NORMAL_INTERVAL = timedelta(seconds=30)
_STATUS_FAST_INTERVAL = timedelta(seconds=5)
_PREDICTION_DATA_INTERVAL = timedelta(hours=1)

_DCEVSE_STATUS_LABELS = {
    1: "Ready",
    2: "Preparing",
    3: "Charging",
}

# Public docs do not describe Sigenergy's SECC run-state enum. These labels are
# intentionally limited to values observed in HAR captures or correlated with
# adjacent V2X telemetry, and unknown values keep the raw state visible.
_SECC_RUN_STATE_LABELS = {
    1: "Idle",
    2: "Establishing communication link",
    3: "Charging",
    8: "Discharging",
    10: "Insulation detection in progress",
}


def _float_or_none(value: Any) -> float | None:
    """Return value as float, or None when the API value is missing/non-numeric."""
    try:
        return float(value)
    except TypeError, ValueError:
        return None


def _directed_charge_power(value: Any) -> float | None:
    """Normalize EVDC charge realtime power to positive charging power."""
    power = _float_or_none(value)
    if power is None:
        return None
    return abs(power)


def _v2x_discharge_power(
    *,
    info_power: float | None,
    realtime_power: float | None,
    discharge_current: float | None,
    secc_run_state: float | None,
) -> float | None:
    """Return positive V2X discharge magnitude, or None when not discharging."""
    if info_power is not None and info_power < -0.05:
        return abs(info_power)
    if secc_run_state == 8:
        for value in (realtime_power, info_power):
            if value is not None and abs(value) > 0.05:
                return abs(value)
        if discharge_current is not None and discharge_current > 0.1:
            return 0.0
    if discharge_current is not None and discharge_current > 0.1:
        for value in (realtime_power, info_power):
            if value is not None and abs(value) > 0.05:
                return abs(value)
        return 0.0
    return None


if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from sigenergy_cloud import SigenergyCloudClient


class SigenSettingsCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Polls device settings every 5 minutes."""

    def __init__(self, hass: HomeAssistant, client: SigenergyCloudClient) -> None:
        super().__init__(
            hass,
            LOGGER,
            name=f"{DOMAIN}_settings",
            update_interval=timedelta(minutes=5),
        )
        self.client = client
        # Maps mode label → (mode_int, profile_id); -1 = no custom profile
        self.available_modes: dict[str, tuple[int, int]] = {}
        # Persists V2X params across setting refreshes; set by the number entities
        self.v2x_power_cap_kw: float | None = None
        self.v2x_duration_minutes: int = 600
        self.v2x_power_cap_kw_by_sn: dict[str, float | None] = {}
        self.v2x_duration_minutes_by_sn: dict[str, int] = {}
        self._prediction_data_cache: dict[str, Any] | None = None
        self._prediction_data_updated_at: datetime | None = None

    def dc_sns(self) -> list[str]:
        """Return known DC charger serial numbers."""
        return list(
            getattr(self.client, "dc_sns", None)
            or ([self.client.dc_sn] if self.client.dc_sn else [])
        )

    def get_v2x_power_cap(self, dc_sn: str) -> float | None:
        """Return the pending V2X power cap for a DC charger."""
        return self.v2x_power_cap_kw_by_sn.get(dc_sn, self.v2x_power_cap_kw)

    def set_v2x_power_cap(self, dc_sn: str, value: float | None) -> None:
        """Set the pending V2X power cap for a DC charger."""
        self.v2x_power_cap_kw_by_sn[dc_sn] = value

    def get_v2x_duration_minutes(self, dc_sn: str) -> int:
        """Return the pending V2X duration for a DC charger."""
        return self.v2x_duration_minutes_by_sn.get(dc_sn, self.v2x_duration_minutes)

    def set_v2x_duration_minutes(self, dc_sn: str, value: int) -> None:
        """Set the pending V2X duration for a DC charger."""
        self.v2x_duration_minutes_by_sn[dc_sn] = value

    async def _prediction_data(self, safe) -> dict[str, Any] | None:
        """Return cached AI prediction data, refreshing it at a slower cadence."""
        now = datetime.now(UTC)
        if (
            self._prediction_data_cache is not None
            and self._prediction_data_updated_at is not None
            and now - self._prediction_data_updated_at < _PREDICTION_DATA_INTERVAL
        ):
            return self._prediction_data_cache

        data = await safe(
            self.client.prediction_data(),
            "prediction_data",
            self._prediction_data_cache,
        )
        if isinstance(data, dict):
            self._prediction_data_cache = data
            self._prediction_data_updated_at = now
        return self._prediction_data_cache

    async def _async_update_data(self) -> dict[str, Any]:
        # Each section is fetched independently; one transient failure
        # shouldn't blank out every entity. Auth failures still bubble.
        async def safe(coro, label, fallback=None):
            try:
                return await coro
            except SigenergyCloudAuthError:
                raise
            except Exception as exc:  # noqa: BLE001
                LOGGER.warning("Sigen settings: %s failed: %s", label, exc)
                # Reuse last known value if we have one, else None.
                if fallback is not None:
                    return fallback
                return (self.data or {}).get(label) if self.data else None

        try:
            if not self.available_modes:
                try:
                    modes_data = await self.client.available_operational_modes()
                    for m in modes_data.get("defaultWorkingModes", []):
                        self.available_modes[m["label"]] = (int(m["value"]), -1)
                    for m in modes_data.get("energyProfileItems", []):
                        self.available_modes[m["name"]] = (9, m["profileId"])
                except SigenergyCloudAuthError:
                    raise
                except Exception as exc:  # noqa: BLE001
                    LOGGER.warning(
                        "Sigen settings: available_operational_modes failed: %s", exc
                    )

            data: dict[str, Any] = {
                "operational_mode": await safe(
                    self.client.current_operational_mode(), "operational_mode"
                ),
                "battery_level": await safe(
                    self.client.battery_levels(), "battery_level"
                ),
                "export_limit": await safe(
                    self.client.grid_export_limit(), "export_limit"
                ),
                "import_limit": await safe(
                    self.client.grid_import_limit(), "import_limit"
                ),
                "battery_export": await safe(
                    self.client.battery_export_limitation(), "battery_export"
                ),
                "prediction_data": await self._prediction_data(safe),
                "prediction_data_fetched_at": (
                    self._prediction_data_updated_at.isoformat()
                    if self._prediction_data_updated_at is not None
                    else None
                ),
                "prediction_data_refresh_interval_minutes": int(
                    _PREDICTION_DATA_INTERVAL.total_seconds() // 60
                ),
                "peak_shaving": await safe(
                    self.client.peak_shaving_schedule(), "peak_shaving"
                ),
                "dc_charge_soc_range": None,
                "dc_charge_mode": None,
                "dc_charge_setting": None,
                "dc_chargers": {},
            }
            dc_chargers: dict[str, dict[str, Any]] = {}
            dc_sns = self.dc_sns()
            if dc_sns:
                data["dc_charge_soc_range"] = await safe(
                    self.client.dc_charge_mode_soc_range(),
                    "dc_charge_soc_range",
                )

            for dc_sn in dc_sns:
                last_dc = ((self.data or {}).get("dc_chargers") or {}).get(dc_sn, {})
                dc_data = {
                    "charge_mode": await safe(
                        self.client.dc_charge_mode(dc_sn=dc_sn),
                        f"dc_charge_mode {dc_sn}",
                        last_dc.get("charge_mode"),
                    ),
                    "charge_setting": await safe(
                        self.client.dc_charge_setting(dc_sn=dc_sn),
                        f"dc_charge_setting {dc_sn}",
                        last_dc.get("charge_setting"),
                    ),
                    "energy_totals": await safe(
                        self.client.dc_energy_totals(dc_sn=dc_sn),
                        f"dc_charger_energy {dc_sn}",
                        last_dc.get("energy_totals"),
                    ),
                    "lifetime_totals": await safe(
                        self.client.dc_lifetime_totals(dc_sn=dc_sn),
                        f"dc_charger_total {dc_sn}",
                        last_dc.get("lifetime_totals"),
                    ),
                    "ocpp_status": await safe(
                        self.client.dc_ocpp_status(dc_sn=dc_sn),
                        f"ocpp_status {dc_sn}",
                        last_dc.get("ocpp_status"),
                    ),
                    "session_records": await safe(
                        self.client.dc_session_records(
                            dc_sn=dc_sn,
                            start_date=date.today() - timedelta(days=30),
                            end_date=date.today(),
                            page=1,
                            page_size=10,
                        ),
                        f"dc_charger_session_records {dc_sn}",
                        last_dc.get("session_records"),
                    ),
                }
                dc_chargers[dc_sn] = dc_data

            active_alarms_payload = await safe(
                self.client.active_alarms(page=1, page_size=10),
                "active_alarms",
            )
            alarms_by_sn: dict[str, list[dict[str, Any]]] = {}
            records = (active_alarms_payload or {}).get("records") or []
            for record in records:
                sn = record.get("deviceSnCode") or record.get("rawDeviceSnCode")
                if not sn:
                    continue
                alarms_by_sn.setdefault(sn, []).append(record)
            for dc_sn in dc_sns:
                dc_chargers[dc_sn]["active_alarms"] = alarms_by_sn.get(dc_sn, [])

            data["dc_chargers"] = dc_chargers
            data["active_alarms"] = active_alarms_payload
            if self.client.dc_sn and self.client.dc_sn in dc_chargers:
                data["dc_charge_mode"] = dc_chargers[self.client.dc_sn]["charge_mode"]
                data["dc_charge_setting"] = dc_chargers[self.client.dc_sn][
                    "charge_setting"
                ]
            return data
        except SigenergyCloudAuthError as exc:
            raise ConfigEntryAuthFailed(exc) from exc
        except SigenergyCloudError as exc:
            raise UpdateFailed(exc) from exc


class SigenStatusCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """
    Polls real-time device status every 30 seconds.

    Covers EV charge power (from energy flow), charging active state,
    and V2X discharge active state. Only calls the DC-charger endpoints
    when a DC charger SN is available.
    """

    def __init__(self, hass: HomeAssistant, client: SigenergyCloudClient) -> None:
        super().__init__(
            hass,
            LOGGER,
            name=f"{DOMAIN}_status",
            update_interval=_STATUS_NORMAL_INTERVAL,
        )
        self.client = client
        self._fast_poll_sources: set[str] = set()

    def dc_sns(self) -> list[str]:
        """Return known DC charger serial numbers."""
        return list(
            getattr(self.client, "dc_sns", None)
            or ([self.client.dc_sn] if self.client.dc_sn else [])
        )

    def set_fast_polling(self, source: str, enabled: bool) -> None:
        """Temporarily increase polling while a charger command is pending."""
        if enabled:
            self._fast_poll_sources.add(source)
        else:
            self._fast_poll_sources.discard(source)
        self.update_interval = (
            _STATUS_FAST_INTERVAL
            if self._fast_poll_sources
            else _STATUS_NORMAL_INTERVAL
        )

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            last = self.data or {}
            try:
                flow = await self.client.energy_flow() or {}
            except SigenergyCloudAuthError:
                raise
            except Exception as exc:  # noqa: BLE001
                LOGGER.warning("Sigen status: energy_flow failed: %s", exc)
                flow = {}
            data: dict[str, Any] = {
                "ev_power": flow.get("evPower", last.get("ev_power")),
                "pv_power": flow.get("pvPower", last.get("pv_power")),
                "grid_power": flow.get("buySellPower", last.get("grid_power")),
                "load_power": flow.get("loadPower", last.get("load_power")),
                "battery_power": flow.get("batteryPower", last.get("battery_power")),
                "battery_soc": flow.get("batterySoc", last.get("battery_soc")),
                "dc_chargers": {},
            }

            dc_sns = self.dc_sns()
            station_is_charging: bool | None = None
            if dc_sns:
                charge_realtime: dict[str, Any] = {}
                try:
                    station_is_charging = await self.client.station_is_charging()
                except SigenergyCloudAuthError:
                    raise
                except Exception as exc:  # noqa: BLE001
                    LOGGER.warning("Sigen status: is_charging failed: %s", exc)
                    station_is_charging = last.get("is_charging")

            dc_chargers: dict[str, dict[str, Any]] = {}
            for dc_sn in dc_sns:
                last_dc = (last.get("dc_chargers") or {}).get(dc_sn, {})
                dc_data: dict[str, Any] = {
                    "is_charging": station_is_charging
                    if len(dc_sns) == 1
                    else last_dc.get("is_charging"),
                    "plugged_in": last_dc.get("plugged_in"),
                    "dc_charge_power": last_dc.get("dc_charge_power"),
                    "ev_soc": last_dc.get("ev_soc"),
                    "secc_run_state": last_dc.get("secc_run_state"),
                    "dc_charger_status": last_dc.get("dc_charger_status"),
                    "v2x_status": last_dc.get("v2x_status"),
                    "current_session_started_at": None,
                    "session_energy_charged": last_dc.get("session_energy_charged"),
                    "lifetime_energy_dispensed": last_dc.get(
                        "lifetime_energy_dispensed"
                    ),
                }
                current_session_start_ts: float | None = None
                try:
                    plug_status = await self.client.dc_plug_status(dc_sn=dc_sn)
                    if plug_status is not None:
                        dc_data["plugged_in"] = bool(plug_status)
                except SigenergyCloudAuthError:
                    raise
                except Exception as exc:  # noqa: BLE001
                    LOGGER.warning(
                        "Sigen status: dc_plug_status %s failed: %s", dc_sn, exc
                    )

                try:
                    charge_realtime = (
                        await self.client.dc_charge_realtime(dc_sn=dc_sn) or {}
                    )
                    dc_data["dc_charge_power"] = (
                        _directed_charge_power(charge_realtime.get("pileOutputPower"))
                        if "pileOutputPower" in charge_realtime
                        else last_dc.get("dc_charge_power")
                    )
                    dc_data["ev_soc"] = charge_realtime.get(
                        "vehicleSoc", last_dc.get("ev_soc")
                    )
                    secc_run_state = charge_realtime.get("seccRunState")
                    if secc_run_state is not None:
                        dc_data["secc_run_state"] = int(secc_run_state)
                        dc_data["dc_charger_status"] = _SECC_RUN_STATE_LABELS.get(
                            int(secc_run_state), f"SECC state {int(secc_run_state)}"
                        )
                    output_power = float(charge_realtime.get("pileOutputPower") or 0)
                    output_current = float(
                        charge_realtime.get("chargingOutputCurrent") or 0
                    )
                    current_session_start_ts = _float_or_none(
                        charge_realtime.get("chargingStartTime")
                    )
                    if _float_or_none(dc_data.get("ev_soc")) not in (None, 0):
                        dc_data["plugged_in"] = True
                    if output_power > 0.05 or output_current > 0.1:
                        dc_data["is_charging"] = True
                    dc_data["session_energy_charged"] = _float_or_none(
                        charge_realtime.get("singleChargePower")
                    )
                    dc_data["lifetime_energy_dispensed"] = _float_or_none(
                        charge_realtime.get("totalChargeEnergy")
                    )
                except SigenergyCloudAuthError:
                    raise
                except Exception as exc:  # noqa: BLE001
                    LOGGER.warning(
                        "Sigen status: dc_charge_realtime %s failed: %s", dc_sn, exc
                    )

                try:
                    charger_status = await self.client.dc_status(dc_sn=dc_sn)
                    if isinstance(charger_status, dict):
                        if not dc_data.get("dc_charger_status"):
                            dc_data["dc_charger_status"] = (
                                charger_status.get("statusDesc")
                                or charger_status.get("status")
                                or last_dc.get("dc_charger_status")
                            )
                    elif charger_status is not None:
                        status_code = int(charger_status)
                        if not dc_data.get("dc_charger_status"):
                            dc_data["dc_charger_status"] = _DCEVSE_STATUS_LABELS.get(
                                status_code, f"Status {status_code}"
                            )
                        if status_code == 3:
                            dc_data["is_charging"] = True
                except SigenergyCloudAuthError:
                    raise
                except Exception as exc:  # noqa: BLE001
                    LOGGER.warning("Sigen status: dc_status %s failed: %s", dc_sn, exc)

                if (
                    dc_data.get("is_charging")
                    and current_session_start_ts is not None
                    and current_session_start_ts > 0
                ):
                    dc_data["current_session_started_at"] = int(
                        current_session_start_ts
                    )

                try:
                    settings = await self.client.v2x_discharge_settings(dc_sn=dc_sn)
                    info = await self.client.v2x_discharge_info(dc_sn=dc_sn)
                    realtime = await self.client.dc_discharge_realtime(dc_sn=dc_sn)

                    if settings:
                        dc_data["v2x_discharge_settings"] = settings
                        discharge_enable = _float_or_none(
                            settings.get("dischargeEnable")
                        )
                        if discharge_enable is not None:
                            dc_data["v2x_discharge_enabled"] = discharge_enable > 0
                        dc_data["v2x_has_car"] = settings.get("hasCar")
                        dc_data["v2x_has_disclaimer"] = settings.get("hasDisclaimer")
                        dc_data["v2x_has_used"] = settings.get("hasUsed")

                    cutout = info.get("evdcCutoutEnableTime") if info else None
                    manual_session = bool(
                        info
                        and info.get("delayCutout") == 1
                        and cutout
                        and cutout > time.time()
                    )
                    secc = _float_or_none(
                        realtime.get("seccRunState") if realtime else None
                    )
                    discharge_power = _float_or_none(
                        info.get("disChargePower") if info else None
                    )
                    realtime_power = _float_or_none(
                        realtime.get("pileOutputPower") if realtime else None
                    )
                    discharge_current = _float_or_none(
                        realtime.get("dischargingOutputCurrent") if realtime else None
                    )
                    discharge_magnitude = _v2x_discharge_power(
                        info_power=discharge_power,
                        realtime_power=realtime_power,
                        discharge_current=discharge_current,
                        secc_run_state=secc,
                    )
                    discharging = discharge_magnitude is not None

                    if discharge_magnitude is not None:
                        dc_data["dc_charge_power"] = -abs(discharge_magnitude)

                    if manual_session and discharging:
                        dc_data["v2x_status"] = "manual"
                    elif manual_session:
                        dc_data["v2x_status"] = "pending"
                    elif discharging:
                        # AI/bidirectional mode — no user-started timed session
                        dc_data["v2x_status"] = "bidirectional"
                    else:
                        dc_data["v2x_status"] = "off"
                except SigenergyCloudAuthError:
                    raise
                except Exception as exc:  # noqa: BLE001
                    LOGGER.warning("Sigen status: V2X status %s failed: %s", dc_sn, exc)

                dc_chargers[dc_sn] = dc_data

            data["dc_chargers"] = dc_chargers
            if self.client.dc_sn and self.client.dc_sn in dc_chargers:
                first_dc = dc_chargers[self.client.dc_sn]
                data["is_charging"] = first_dc.get("is_charging")
                data["dc_charge_power"] = first_dc.get("dc_charge_power")
                data["ev_soc"] = first_dc.get("ev_soc")
                data["plugged_in"] = first_dc.get("plugged_in")
                data["secc_run_state"] = first_dc.get("secc_run_state")
                data["dc_charger_status"] = first_dc.get("dc_charger_status")
                data["v2x_status"] = first_dc.get("v2x_status")

            return data
        except SigenergyCloudAuthError as exc:
            raise ConfigEntryAuthFailed(exc) from exc
        except SigenergyCloudError as exc:
            raise UpdateFailed(exc) from exc
        except Exception as exc:
            raise UpdateFailed(exc) from exc
