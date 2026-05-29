"""DataUpdateCoordinators for Sigenergy."""

from __future__ import annotations

import time
from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING, Any

from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from sigenergy_cloud import (
    SigenergyCloudAuthError,
    SigenergyCloudError,
    SigenergyCloudRateLimitError,
)

from .const import DOMAIN, LOGGER

_SETTINGS_INTERVAL = timedelta(minutes=15)
_STATUS_NORMAL_INTERVAL = timedelta(minutes=2)
_STATUS_FAST_INTERVAL = timedelta(seconds=15)
_PREDICTION_DATA_INTERVAL = timedelta(hours=1)
_RATE_LIMIT_BACKOFF_INTERVAL = timedelta(minutes=30)
_DC_PLUG_STATUS_IDLE_INTERVAL = timedelta(minutes=10)
_DC_REALTIME_IDLE_INTERVAL = timedelta(minutes=10)
_DC_STATUS_IDLE_INTERVAL = timedelta(minutes=10)
_DC_V2X_IDLE_INTERVAL = timedelta(minutes=10)
_DC_SLOW_INTERVAL = timedelta(hours=1)
_DC_RARE_INTERVAL = timedelta(hours=6)
_ACTIVE_ALARMS_INTERVAL = timedelta(minutes=30)
_RATE_LIMIT_BACKOFF_UNTIL = 0.0
_DC_STATUS_CARRY_FORWARD_KEYS = (
    "plugged_in",
    "dc_charge_power",
    "ev_soc",
    "secc_run_state",
    "dc_charger_status",
    "v2x_status",
    "v2x_discharge_enabled",
    "v2x_has_car",
    "v2x_has_disclaimer",
    "v2x_has_used",
    "v2x_discharge_settings",
    "current_session_started_at",
    "session_energy_charged",
    "lifetime_energy_dispensed",
)


class _RateLimitBackoff(Exception):
    """Raised internally to abort an update after the cloud rate-limits us."""


def _rate_limit_backoff_remaining() -> float:
    """Return remaining shared cloud-polling backoff seconds."""
    return max(0.0, _RATE_LIMIT_BACKOFF_UNTIL - time.monotonic())


def _activate_rate_limit_backoff(label: str, exc: Exception) -> None:
    """Start a shared cooldown after Sigenergy rate-limits a request."""
    global _RATE_LIMIT_BACKOFF_UNTIL  # noqa: PLW0603

    until = time.monotonic() + _RATE_LIMIT_BACKOFF_INTERVAL.total_seconds()
    if until > _RATE_LIMIT_BACKOFF_UNTIL:
        _RATE_LIMIT_BACKOFF_UNTIL = until
        LOGGER.warning(
            "Sigen cloud rate-limited %s; backing off polling for %.0f minutes: %s",
            label,
            _RATE_LIMIT_BACKOFF_INTERVAL.total_seconds() / 60,
            exc,
        )

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
    except (TypeError, ValueError):
        return None


def _is_recent(updated_at: float | None, interval: timedelta) -> bool:
    """Return true when a monotonic timestamp is still inside an interval."""
    return (
        updated_at is not None
        and time.monotonic() - updated_at < interval.total_seconds()
    )


def _status_dc_data_from_last(
    last_dc: dict[str, Any],
    *,
    station_is_charging: bool | None,
    single_dc: bool,
) -> dict[str, Any]:
    """Seed DC status data with last-known slow fields between endpoint polls."""
    dc_data = {key: last_dc.get(key) for key in _DC_STATUS_CARRY_FORWARD_KEYS}
    dc_data["is_charging"] = (
        station_is_charging
        if single_dc and station_is_charging is not None
        else last_dc.get("is_charging")
    )
    return dc_data


def _energy_flow_pv_power(flow: dict[str, Any], last: dict[str, Any]) -> float | None:
    """Return total station PV power, including Sigenergy's third-party PV field."""
    native_pv_power = _float_or_none(flow.get("pvPower"))
    third_party_pv_power = _float_or_none(flow.get("thirdPvPower"))
    if native_pv_power is None and third_party_pv_power is None:
        return last.get("pv_power")
    return (native_pv_power or 0.0) + (third_party_pv_power or 0.0)


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
    """Polls device settings at a conservative cadence."""

    def __init__(self, hass: HomeAssistant, client: SigenergyCloudClient) -> None:
        super().__init__(
            hass,
            LOGGER,
            name=f"{DOMAIN}_settings",
            update_interval=_SETTINGS_INTERVAL,
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
        self._slow_cache: dict[str, Any] = {}
        self._slow_cache_updated_at: dict[str, datetime] = {}

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

    def async_update_local_data(self, updates: dict[str, Any]) -> None:
        """Apply optimistic setting data after a successful cloud write."""
        data = dict(self.data or {})
        data.update(updates)
        self.async_set_updated_data(data)

    def async_update_local_dc_data(self, dc_sn: str, updates: dict[str, Any]) -> None:
        """Apply optimistic DC-charger setting data after a successful cloud write."""
        data = dict(self.data or {})
        dc_chargers = dict(data.get("dc_chargers") or {})
        dc_data = dict(dc_chargers.get(dc_sn) or {})
        dc_data.update(updates)
        dc_chargers[dc_sn] = dc_data
        data["dc_chargers"] = dc_chargers
        if self.client.dc_sn == dc_sn:
            if "charge_mode" in updates:
                data["dc_charge_mode"] = updates["charge_mode"]
            if "charge_setting" in updates:
                data["dc_charge_setting"] = updates["charge_setting"]
        self.async_set_updated_data(data)

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

    async def _cached_data(
        self,
        safe,
        label: str,
        factory,
        interval: timedelta,
        fallback=None,
    ) -> Any:
        """Return a cached slow payload, refreshing only after its own interval."""
        now = datetime.now(UTC)
        updated_at = self._slow_cache_updated_at.get(label)
        if (
            label in self._slow_cache
            and updated_at is not None
            and now - updated_at < interval
        ):
            return self._slow_cache[label]

        data = await safe(factory(), label, self._slow_cache.get(label, fallback))
        if data is not None:
            self._slow_cache[label] = data
            self._slow_cache_updated_at[label] = now
        return data

    async def _async_update_data(self) -> dict[str, Any]:
        if _rate_limit_backoff_remaining():
            return self.data or {}

        # Each section is fetched independently; one transient failure
        # shouldn't blank out every entity. Auth failures still bubble.
        async def safe(coro, label, fallback=None):
            try:
                return await coro
            except SigenergyCloudAuthError:
                raise
            except SigenergyCloudRateLimitError as exc:
                _activate_rate_limit_backoff(f"Sigen settings: {label}", exc)
                raise _RateLimitBackoff from exc
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
                except SigenergyCloudRateLimitError as exc:
                    _activate_rate_limit_backoff(
                        "Sigen settings: available_operational_modes", exc
                    )
                    raise _RateLimitBackoff from exc
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
                "instant_manual": await safe(
                    self.client.instant_manual_control(), "instant_manual"
                ),
                "instant_manual_display": await safe(
                    self.client.instant_manual_display(),
                    "instant_manual_display",
                    (self.data or {}).get("instant_manual_display"),
                ),
                "dc_charge_soc_range": None,
                "dc_charge_mode": None,
                "dc_charge_setting": None,
                "dc_chargers": {},
            }
            dc_chargers: dict[str, dict[str, Any]] = {}
            dc_sns = self.dc_sns()
            if dc_sns:
                data["dc_charge_soc_range"] = await self._cached_data(
                    safe,
                    "dc_charge_soc_range",
                    self.client.dc_charge_mode_soc_range,
                    _DC_RARE_INTERVAL,
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
                    "energy_totals": await self._cached_data(
                        safe,
                        f"dc_charger_energy {dc_sn}",
                        lambda dc_sn=dc_sn: self.client.dc_energy_totals(dc_sn=dc_sn),
                        _DC_SLOW_INTERVAL,
                        last_dc.get("energy_totals"),
                    ),
                    "lifetime_totals": await self._cached_data(
                        safe,
                        f"dc_charger_total {dc_sn}",
                        lambda dc_sn=dc_sn: self.client.dc_lifetime_totals(dc_sn=dc_sn),
                        _DC_RARE_INTERVAL,
                        last_dc.get("lifetime_totals"),
                    ),
                    "ocpp_status": await self._cached_data(
                        safe,
                        f"ocpp_status {dc_sn}",
                        lambda dc_sn=dc_sn: self.client.dc_ocpp_status(dc_sn=dc_sn),
                        _DC_SLOW_INTERVAL,
                        last_dc.get("ocpp_status"),
                    ),
                    "session_records": await self._cached_data(
                        safe,
                        f"dc_charger_session_records {dc_sn}",
                        lambda dc_sn=dc_sn: self.client.dc_session_records(
                            dc_sn=dc_sn,
                            start_date=date.today() - timedelta(days=30),
                            end_date=date.today(),
                            page=1,
                            page_size=10,
                        ),
                        _DC_SLOW_INTERVAL,
                        last_dc.get("session_records"),
                    ),
                }
                dc_chargers[dc_sn] = dc_data

            active_alarms_payload = await self._cached_data(
                safe,
                "active_alarms",
                lambda: self.client.active_alarms(page=1, page_size=10),
                _ACTIVE_ALARMS_INTERVAL,
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
        except _RateLimitBackoff as exc:
            if self.data is not None:
                return self.data
            raise UpdateFailed(exc) from exc
        except SigenergyCloudAuthError as exc:
            raise ConfigEntryAuthFailed(exc) from exc
        except SigenergyCloudError as exc:
            raise UpdateFailed(exc) from exc


class SigenStatusCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """
    Polls real-time device status at a conservative cadence.

    The station energy-flow endpoint is still the regular live signal. Heavier
    DC-charger and V2X endpoints are refreshed faster only while activity or a
    pending command is visible.
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
        self._plug_status_updated_at: dict[str, float] = {}
        self._dc_realtime_updated_at: dict[str, float] = {}
        self._dc_status_updated_at: dict[str, float] = {}
        self._dc_v2x_updated_at: dict[str, float] = {}

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

    def _should_refresh(
        self,
        updated_by_sn: dict[str, float],
        dc_sn: str,
        interval: timedelta,
        *,
        force: bool = False,
    ) -> bool:
        return force or not _is_recent(updated_by_sn.get(dc_sn), interval)

    @staticmethod
    def _mark_refreshed(updated_by_sn: dict[str, float], dc_sn: str) -> None:
        updated_by_sn[dc_sn] = time.monotonic()

    async def _async_update_data(self) -> dict[str, Any]:
        if _rate_limit_backoff_remaining():
            return self.data or {}

        try:
            last = self.data or {}
            try:
                flow = await self.client.energy_flow() or {}
            except SigenergyCloudAuthError:
                raise
            except SigenergyCloudRateLimitError as exc:
                _activate_rate_limit_backoff("Sigen status: energy_flow", exc)
                raise _RateLimitBackoff from exc
            except Exception as exc:  # noqa: BLE001
                LOGGER.warning("Sigen status: energy_flow failed: %s", exc)
                flow = {}
            data: dict[str, Any] = {
                "ev_power": flow.get("evPower", last.get("ev_power")),
                "pv_power": _energy_flow_pv_power(flow, last),
                "native_pv_power": (
                    _float_or_none(flow.get("pvPower"))
                    if "pvPower" in flow
                    else last.get("native_pv_power")
                ),
                "third_party_pv_power": (
                    _float_or_none(flow.get("thirdPvPower"))
                    if "thirdPvPower" in flow
                    else last.get("third_party_pv_power")
                ),
                "grid_power": flow.get("buySellPower", last.get("grid_power")),
                "load_power": flow.get("loadPower", last.get("load_power")),
                "battery_power": flow.get("batteryPower", last.get("battery_power")),
                "battery_soc": flow.get("batterySoc", last.get("battery_soc")),
                "dc_chargers": {},
            }

            dc_sns = self.dc_sns()
            station_is_charging: bool | None = None
            fast_polling = bool(self._fast_poll_sources)
            ev_power = _float_or_none(data.get("ev_power"))
            dc_last_values = (last.get("dc_chargers") or {}).values()
            v2x_statuses = {"manual", "pending", "bidirectional"}
            station_activity_hint = (
                fast_polling
                or (ev_power is not None and abs(ev_power) > 0.05)
                or any(
                    bool(dc.get("is_charging"))
                    or dc.get("v2x_status") in v2x_statuses
                    for dc in dc_last_values
                )
            )
            if dc_sns and station_activity_hint:
                try:
                    station_is_charging = await self.client.station_is_charging()
                except SigenergyCloudAuthError:
                    raise
                except SigenergyCloudRateLimitError as exc:
                    _activate_rate_limit_backoff("Sigen status: is_charging", exc)
                    raise _RateLimitBackoff from exc
                except Exception as exc:  # noqa: BLE001
                    LOGGER.warning("Sigen status: is_charging failed: %s", exc)
                    station_is_charging = last.get("is_charging")

            dc_chargers: dict[str, dict[str, Any]] = {}
            for dc_sn in dc_sns:
                last_dc = (last.get("dc_chargers") or {}).get(dc_sn, {})
                dc_data = _status_dc_data_from_last(
                    last_dc,
                    station_is_charging=station_is_charging,
                    single_dc=len(dc_sns) == 1,
                )
                dc_active = (
                    fast_polling
                    or (ev_power is not None and abs(ev_power) > 0.05)
                    or bool(last_dc.get("is_charging"))
                    or last_dc.get("v2x_status") in v2x_statuses
                )
                v2x_active = last_dc.get("v2x_status") in v2x_statuses
                current_session_start_ts: float | None = None
                if self._should_refresh(
                    self._plug_status_updated_at,
                    dc_sn,
                    _DC_PLUG_STATUS_IDLE_INTERVAL,
                    force=dc_active,
                ):
                    try:
                        plug_status = await self.client.dc_plug_status(dc_sn=dc_sn)
                        self._mark_refreshed(self._plug_status_updated_at, dc_sn)
                        if plug_status is not None:
                            dc_data["plugged_in"] = bool(plug_status)
                    except SigenergyCloudAuthError:
                        raise
                    except SigenergyCloudRateLimitError as exc:
                        _activate_rate_limit_backoff(
                            f"Sigen status: dc_plug_status {dc_sn}", exc
                        )
                        raise _RateLimitBackoff from exc
                    except Exception as exc:  # noqa: BLE001
                        LOGGER.warning(
                            "Sigen status: dc_plug_status %s failed: %s", dc_sn, exc
                        )

                if self._should_refresh(
                    self._dc_realtime_updated_at,
                    dc_sn,
                    _DC_REALTIME_IDLE_INTERVAL,
                    force=dc_active,
                ):
                    try:
                        charge_realtime = (
                            await self.client.dc_charge_realtime(dc_sn=dc_sn) or {}
                        )
                        self._mark_refreshed(self._dc_realtime_updated_at, dc_sn)
                        dc_data["dc_charge_power"] = (
                            _directed_charge_power(
                                charge_realtime.get("pileOutputPower")
                            )
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
                        output_power = float(
                            charge_realtime.get("pileOutputPower") or 0
                        )
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
                        elif station_is_charging is False:
                            dc_data["is_charging"] = False
                        dc_data["session_energy_charged"] = _float_or_none(
                            charge_realtime.get("singleChargePower")
                        )
                        dc_data["lifetime_energy_dispensed"] = _float_or_none(
                            charge_realtime.get("totalChargeEnergy")
                        )
                    except SigenergyCloudAuthError:
                        raise
                    except SigenergyCloudRateLimitError as exc:
                        _activate_rate_limit_backoff(
                            f"Sigen status: dc_charge_realtime {dc_sn}", exc
                        )
                        raise _RateLimitBackoff from exc
                    except Exception as exc:  # noqa: BLE001
                        LOGGER.warning(
                            "Sigen status: dc_charge_realtime %s failed: %s",
                            dc_sn,
                            exc,
                        )

                if self._should_refresh(
                    self._dc_status_updated_at,
                    dc_sn,
                    _DC_STATUS_IDLE_INTERVAL,
                    force=dc_active,
                ):
                    try:
                        charger_status = await self.client.dc_status(dc_sn=dc_sn)
                        self._mark_refreshed(self._dc_status_updated_at, dc_sn)
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
                                dc_data["dc_charger_status"] = (
                                    _DCEVSE_STATUS_LABELS.get(
                                        status_code, f"Status {status_code}"
                                    )
                                )
                            if status_code == 3:
                                dc_data["is_charging"] = True
                    except SigenergyCloudAuthError:
                        raise
                    except SigenergyCloudRateLimitError as exc:
                        _activate_rate_limit_backoff(
                            f"Sigen status: dc_status {dc_sn}", exc
                        )
                        raise _RateLimitBackoff from exc
                    except Exception as exc:  # noqa: BLE001
                        LOGGER.warning(
                            "Sigen status: dc_status %s failed: %s", dc_sn, exc
                        )

                if not dc_data.get("is_charging"):
                    dc_data["current_session_started_at"] = None
                elif current_session_start_ts is not None and current_session_start_ts > 0:
                    dc_data["current_session_started_at"] = int(
                        current_session_start_ts
                    )

                if self._should_refresh(
                    self._dc_v2x_updated_at,
                    dc_sn,
                    _DC_V2X_IDLE_INTERVAL,
                    force=fast_polling or v2x_active,
                ):
                    try:
                        settings = await self.client.v2x_discharge_settings(
                            dc_sn=dc_sn
                        )
                        info = await self.client.v2x_discharge_info(dc_sn=dc_sn)
                        realtime = await self.client.dc_discharge_realtime(dc_sn=dc_sn)
                        self._mark_refreshed(self._dc_v2x_updated_at, dc_sn)

                        if settings:
                            dc_data["v2x_discharge_settings"] = settings
                            discharge_enable = _float_or_none(
                                settings.get("dischargeEnable")
                            )
                            if discharge_enable is not None:
                                dc_data["v2x_discharge_enabled"] = discharge_enable > 0
                            dc_data["v2x_has_car"] = settings.get("hasCar")
                            dc_data["v2x_has_disclaimer"] = settings.get(
                                "hasDisclaimer"
                            )
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
                            realtime.get("dischargingOutputCurrent")
                            if realtime
                            else None
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
                    except SigenergyCloudRateLimitError as exc:
                        _activate_rate_limit_backoff(
                            f"Sigen status: V2X status {dc_sn}", exc
                        )
                        raise _RateLimitBackoff from exc
                    except Exception as exc:  # noqa: BLE001
                        LOGGER.warning(
                            "Sigen status: V2X status %s failed: %s", dc_sn, exc
                        )

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
        except _RateLimitBackoff as exc:
            if self.data is not None:
                return self.data
            raise UpdateFailed(exc) from exc
        except SigenergyCloudAuthError as exc:
            raise ConfigEntryAuthFailed(exc) from exc
        except SigenergyCloudError as exc:
            raise UpdateFailed(exc) from exc
        except Exception as exc:
            raise UpdateFailed(exc) from exc
