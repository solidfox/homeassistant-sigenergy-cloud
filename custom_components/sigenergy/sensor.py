"""Sensor platform for Sigenergy cloud status."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE, UnitOfEnergy, UnitOfPower

from .entity import (
    SigenDCChargerSettingsEntity,
    SigenDCChargerStatusEntity,
    SigenStatusEntity,
)

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

    from .coordinator import SigenSettingsCoordinator, SigenStatusCoordinator
    from .data import SigenConfigEntry


@dataclass(frozen=True, kw_only=True)
class SigenSensorDescription(SensorEntityDescription):
    """Description for a status coordinator backed sensor."""

    data_key: str


@dataclass(frozen=True, kw_only=True)
class SigenLastSessionFieldDescription(SensorEntityDescription):
    """Description for one normalized field from the last session record."""

    value_key: str
    attribute_description: str


ENERGY_FLOW_SENSORS: tuple[SigenSensorDescription, ...] = (
    SigenSensorDescription(
        key="ev_power",
        data_key="ev_power",
        translation_key="ev_power",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        icon="mdi:ev-station",
    ),
    SigenSensorDescription(
        key="pv_power",
        data_key="pv_power",
        translation_key="pv_power",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        icon="mdi:solar-power",
    ),
    SigenSensorDescription(
        key="grid_power",
        data_key="grid_power",
        translation_key="grid_power",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        icon="mdi:transmission-tower",
    ),
    SigenSensorDescription(
        key="load_power",
        data_key="load_power",
        translation_key="load_power",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        icon="mdi:home-lightning-bolt",
    ),
    SigenSensorDescription(
        key="battery_power",
        data_key="battery_power",
        translation_key="battery_power",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        icon="mdi:battery-charging",
    ),
    SigenSensorDescription(
        key="battery_soc",
        data_key="battery_soc",
        translation_key="battery_soc",
        device_class=SensorDeviceClass.BATTERY,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
    ),
)


DC_CHARGER_SENSORS: tuple[SigenSensorDescription, ...] = (
    SigenSensorDescription(
        key="dc_charge_power",
        data_key="dc_charge_power",
        translation_key="dc_charge_power",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        icon="mdi:ev-station",
    ),
    SigenSensorDescription(
        key="ev_soc",
        data_key="ev_soc",
        translation_key="ev_soc",
        device_class=SensorDeviceClass.BATTERY,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
        icon="mdi:car-electric",
    ),
    SigenSensorDescription(
        key="secc_run_state",
        data_key="secc_run_state",
        translation_key="secc_run_state",
        icon="mdi:chip",
    ),
    SigenSensorDescription(
        key="session_energy_charged",
        data_key="session_energy_charged",
        translation_key="dc_charger_session_energy_charged",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        icon="mdi:battery-charging-high",
    ),
    SigenSensorDescription(
        key="lifetime_energy_dispensed",
        data_key="lifetime_energy_dispensed",
        translation_key="dc_charger_lifetime_energy_dispensed",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        icon="mdi:counter",
    ),
)


DC_CHARGER_ENERGY_TOTAL_SENSORS: tuple[tuple[str, str, str], ...] = (
    ("weekly_energy", "weeklyEnergy", "dc_charger_weekly_energy"),
    ("monthly_energy", "monthlyEnergy", "dc_charger_monthly_energy"),
    ("lifetime_energy", "lifetimeEnergy", "dc_charger_lifetime_energy"),
)

DC_CHARGER_LIFETIME_TOTAL_SENSORS: tuple[tuple[str, str, str, str], ...] = (
    (
        "total_energy_charged",
        "totalChargeEnergy",
        "dc_charger_total_energy_charged",
        "mdi:battery-charging-high",
    ),
    (
        "total_energy_discharged",
        "totalDischargeEnergy",
        "dc_charger_total_energy_discharged",
        "mdi:battery-arrow-down",
    ),
)


DC_CHARGER_LAST_SESSION_FIELD_SENSORS: tuple[SigenLastSessionFieldDescription, ...] = (
    SigenLastSessionFieldDescription(
        key="last_session_record_id",
        value_key="record_id",
        translation_key="dc_charger_last_session_record_id",
        icon="mdi:identifier",
        attribute_description=(
            "Sigenergy identifier for the last completed EVDC charge/discharge "
            "session. Useful for correlating journal history with raw session "
            "records."
        ),
    ),
    SigenLastSessionFieldDescription(
        key="last_session_started",
        value_key="start_time",
        translation_key="dc_charger_last_session_started",
        icon="mdi:clock-start",
        attribute_description=(
            "Displayed start time for the last completed EVDC session, taken from "
            "the Sigenergy session-history record."
        ),
    ),
    SigenLastSessionFieldDescription(
        key="last_session_ended",
        value_key="end_time",
        translation_key="dc_charger_last_session_ended",
        icon="mdi:clock-end",
        attribute_description=(
            "Displayed end time for the last completed EVDC session, taken from "
            "the Sigenergy session-history record."
        ),
    ),
    SigenLastSessionFieldDescription(
        key="last_session_duration",
        value_key="duration_minutes",
        translation_key="dc_charger_last_session_duration",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="min",
        icon="mdi:timer-outline",
        attribute_description=(
            "Duration of the last completed EVDC session in minutes. The cloud "
            "field is named singleChargingTime and is reported in seconds."
        ),
    ),
    SigenLastSessionFieldDescription(
        key="last_session_energy_charged",
        value_key="energy_in_kwh",
        translation_key="dc_charger_last_session_energy_charged",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        icon="mdi:battery-plus",
        attribute_description=(
            "Energy reported by Sigenergy for charging during the last completed "
            "EVDC session. Some payloads name this field singleChargingPower "
            "even though it behaves like a per-session amount."
        ),
    ),
    SigenLastSessionFieldDescription(
        key="last_session_energy_discharged",
        value_key="energy_out_kwh",
        translation_key="dc_charger_last_session_energy_discharged",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        icon="mdi:battery-minus",
        attribute_description=(
            "Energy reported by Sigenergy as discharged from the EV during the "
            "last completed EVDC session."
        ),
    ),
    SigenLastSessionFieldDescription(
        key="last_session_start_soc",
        value_key="start_soc",
        translation_key="dc_charger_last_session_start_soc",
        device_class=SensorDeviceClass.BATTERY,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
        icon="mdi:battery-arrow-up",
        attribute_description=(
            "EV state of charge at the start of the last completed EVDC session."
        ),
    ),
    SigenLastSessionFieldDescription(
        key="last_session_end_soc",
        value_key="end_soc",
        translation_key="dc_charger_last_session_end_soc",
        device_class=SensorDeviceClass.BATTERY,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
        icon="mdi:battery-arrow-down",
        attribute_description=(
            "EV state of charge at the end of the last completed EVDC session."
        ),
    ),
    SigenLastSessionFieldDescription(
        key="last_session_end_reason",
        value_key="end_reason",
        translation_key="dc_charger_last_session_end_reason",
        icon="mdi:message-alert-outline",
        attribute_description=(
            "Human-readable stop reason Sigenergy reported for the last completed "
            "EVDC session."
        ),
    ),
    SigenLastSessionFieldDescription(
        key="last_session_stop_code",
        value_key="end_code",
        translation_key="dc_charger_last_session_stop_code",
        icon="mdi:numeric",
        attribute_description=(
            "Sigenergy stop code for the last completed EVDC session. This is the "
            "raw chargingEndCode/endCode-style field and is useful for "
            "correlating session stops with app or alarm behavior."
        ),
    ),
    SigenLastSessionFieldDescription(
        key="last_session_alarm_code",
        value_key="alarm_code",
        translation_key="dc_charger_last_session_alarm_code",
        icon="mdi:alert-circle-outline",
        attribute_description=(
            "Alarm or error code reported on the last completed EVDC session "
            "when the cloud record includes one."
        ),
    ),
    SigenLastSessionFieldDescription(
        key="last_session_alarm_name",
        value_key="alarm_name",
        translation_key="dc_charger_last_session_alarm_name",
        icon="mdi:alert-decagram-outline",
        attribute_description=(
            "Alarm or error name reported on the last completed EVDC session "
            "when the cloud record includes one."
        ),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SigenConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Sigenergy sensor entities."""
    data = entry.runtime_data
    entities: list[SensorEntity] = [
        SigenEnergyFlowSensor(
            data.status_coordinator,
            data.client.station_id,
            description,
        )
        for description in ENERGY_FLOW_SENSORS
    ]
    for dc_sn in data.status_coordinator.dc_sns():
        entities.extend(
            SigenDCChargerNumericSensor(
                data.status_coordinator,
                data.client.station_id,
                dc_sn,
                description,
            )
            for description in DC_CHARGER_SENSORS
        )
        entities.extend(
            [
                SigenDCChargerStatusSensor(
                    data.status_coordinator,
                    data.client.station_id,
                    dc_sn,
                ),
                SigenV2XStatusSensor(
                    data.status_coordinator,
                    data.client.station_id,
                    dc_sn,
                ),
                SigenDCChargerCurrentSessionStartedAtSensor(
                    data.status_coordinator,
                    data.client.station_id,
                    dc_sn,
                ),
            ]
        )

    for dc_sn in data.settings_coordinator.dc_sns():
        for key, payload_key, translation_key in DC_CHARGER_ENERGY_TOTAL_SENSORS:
            entities.append(
                SigenDCChargerEnergyTotalSensor(
                    data.settings_coordinator,
                    data.client.station_id,
                    dc_sn,
                    key=key,
                    payload_key=payload_key,
                    translation_key=translation_key,
                )
            )
        for (
            key,
            payload_key,
            translation_key,
            icon,
        ) in DC_CHARGER_LIFETIME_TOTAL_SENSORS:
            entities.append(
                SigenDCChargerLifetimeTotalSensor(
                    data.settings_coordinator,
                    data.client.station_id,
                    dc_sn,
                    key=key,
                    payload_key=payload_key,
                    translation_key=translation_key,
                    icon=icon,
                )
            )
        entities.append(
            SigenDCChargerActiveAlarmSensor(
                data.settings_coordinator,
                data.client.station_id,
                dc_sn,
            )
        )
        entities.append(
            SigenDCChargerOCPPStatusSensor(
                data.settings_coordinator,
                data.client.station_id,
                dc_sn,
            )
        )
        entities.append(
            SigenDCChargerLastSessionSensor(
                data.settings_coordinator,
                data.client.station_id,
                dc_sn,
            )
        )
        entities.extend(
            SigenDCChargerLastSessionFieldSensor(
                data.settings_coordinator,
                data.client.station_id,
                dc_sn,
                description,
            )
            for description in DC_CHARGER_LAST_SESSION_FIELD_SENSORS
        )

    async_add_entities(entities)


class SigenEnergyFlowSensor(SigenStatusEntity, SensorEntity):
    """Numeric sensor from the energy flow endpoint."""

    entity_description: SigenSensorDescription

    def __init__(
        self,
        coordinator: SigenStatusCoordinator,
        station_id: str,
        description: SigenSensorDescription,
    ) -> None:
        super().__init__(coordinator, station_id, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> float | None:
        if self.coordinator.data is None:
            return None
        val = self.coordinator.data.get(self.entity_description.data_key)
        return float(val) if val is not None else None


class SigenDCChargerNumericSensor(SigenDCChargerStatusEntity, SensorEntity):
    """Numeric sensor from a DC charger realtime endpoint."""

    entity_description: SigenSensorDescription

    def __init__(
        self,
        coordinator: SigenStatusCoordinator,
        station_id: str,
        dc_sn: str,
        description: SigenSensorDescription,
    ) -> None:
        super().__init__(coordinator, station_id, dc_sn, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> float | int | None:
        if self.coordinator.data is None:
            return None
        dc_data = (self.coordinator.data.get("dc_chargers") or {}).get(self._dc_sn, {})
        val = dc_data.get(self.entity_description.data_key)
        if val is None:
            return None
        if self.entity_description.data_key == "secc_run_state":
            return int(val)
        return float(val)


class SigenDCChargerStatusSensor(SigenDCChargerStatusEntity, SensorEntity):
    """Text status reported by the DC charger status endpoint."""

    _attr_translation_key = "dc_charger_status"
    _attr_icon = "mdi:ev-station"

    def __init__(
        self,
        coordinator: SigenStatusCoordinator,
        station_id: str,
        dc_sn: str,
    ) -> None:
        super().__init__(coordinator, station_id, dc_sn, "dc_charger_status")

    @property
    def native_value(self) -> str | None:
        if self.coordinator.data is None:
            return None
        dc_data = (self.coordinator.data.get("dc_chargers") or {}).get(self._dc_sn, {})
        value = dc_data.get("dc_charger_status")
        return str(value) if value is not None else None


class SigenV2XStatusSensor(SigenDCChargerStatusEntity, SensorEntity):
    """V2X discharge status from session and realtime endpoints."""

    _attr_translation_key = "v2x_status"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = ["off", "pending", "manual", "bidirectional"]
    _attr_icon = "mdi:car-electric"

    def __init__(
        self,
        coordinator: SigenStatusCoordinator,
        station_id: str,
        dc_sn: str,
    ) -> None:
        super().__init__(coordinator, station_id, dc_sn, "v2x_status")

    @property
    def native_value(self) -> str | None:
        if self.coordinator.data is None:
            return None
        dc_data = (self.coordinator.data.get("dc_chargers") or {}).get(self._dc_sn, {})
        return dc_data.get("v2x_status")


class SigenDCChargerCurrentSessionStartedAtSensor(
    SigenDCChargerStatusEntity, SensorEntity
):
    """Timestamp for the active charging session, if one is currently running."""

    _attr_translation_key = "dc_charger_current_session_started_at"
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_icon = "mdi:clock-start"

    def __init__(
        self,
        coordinator: SigenStatusCoordinator,
        station_id: str,
        dc_sn: str,
    ) -> None:
        super().__init__(
            coordinator, station_id, dc_sn, "dc_charger_current_session_started_at"
        )

    @property
    def native_value(self) -> datetime | None:
        if self.coordinator.data is None:
            return None
        dc_data = (self.coordinator.data.get("dc_chargers") or {}).get(self._dc_sn, {})
        ts = dc_data.get("current_session_started_at")
        if ts is None:
            return None
        return datetime.fromtimestamp(int(ts), tz=UTC)


class SigenDCChargerEnergyTotalSensor(SigenDCChargerSettingsEntity, SensorEntity):
    """Cumulative energy totals (week/month/lifetime) from the dcevse energy endpoint."""

    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_icon = "mdi:counter"

    def __init__(
        self,
        coordinator: SigenSettingsCoordinator,
        station_id: str,
        dc_sn: str,
        *,
        key: str,
        payload_key: str,
        translation_key: str,
    ) -> None:
        super().__init__(coordinator, station_id, dc_sn, key)
        self._payload_key = payload_key
        self._attr_translation_key = translation_key

    @property
    def native_value(self) -> float | None:
        if self.coordinator.data is None:
            return None
        dc_data = (self.coordinator.data.get("dc_chargers") or {}).get(self._dc_sn, {})
        totals = dc_data.get("energy_totals") or {}
        value = totals.get(self._payload_key)
        return float(value) if value is not None else None


class SigenDCChargerLifetimeTotalSensor(SigenDCChargerSettingsEntity, SensorEntity):
    """Lifetime charged/discharged totals from the dcevse total endpoint."""

    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR

    def __init__(
        self,
        coordinator: SigenSettingsCoordinator,
        station_id: str,
        dc_sn: str,
        *,
        key: str,
        payload_key: str,
        translation_key: str,
        icon: str,
    ) -> None:
        super().__init__(coordinator, station_id, dc_sn, key)
        self._payload_key = payload_key
        self._attr_translation_key = translation_key
        self._attr_icon = icon

    @property
    def native_value(self) -> float | None:
        if self.coordinator.data is None:
            return None
        dc_data = (self.coordinator.data.get("dc_chargers") or {}).get(self._dc_sn, {})
        totals = dc_data.get("lifetime_totals") or {}
        value = totals.get(self._payload_key)
        return float(value) if value is not None else None


_OCPP_LINK_STATUS_LABELS = {
    0: "Disconnected",
    1: "Connected",
    2: "Connecting",
}


def _session_records(payload: Any) -> list[dict[str, Any]]:
    """Return session records from known Sigenergy page envelope shapes."""
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []
    for key in ("records", "list", "rows", "items"):
        records = payload.get(key)
        if isinstance(records, list):
            return [item for item in records if isinstance(item, dict)]
    data = payload.get("data")
    if isinstance(data, dict):
        return _session_records(data)
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    return []


def _first_value(record: dict[str, Any], *keys: str) -> Any:
    """Return the first present non-empty value from a session record."""
    match = _first_key_value(record, *keys)
    return match[1] if match else None


def _first_key_value(record: dict[str, Any], *keys: str) -> tuple[str, Any] | None:
    """Return the first present non-empty key/value pair from a session record."""
    for key in keys:
        value = record.get(key)
        if value not in (None, ""):
            return key, value
    return None


def _float_value(value: Any) -> float | None:
    """Return value as float when possible."""
    if value in (None, ""):
        return None
    try:
        return float(value)
    except TypeError, ValueError:
        return None


def _rounded(value: float | None, decimals: int = 2) -> float | None:
    """Round a float while preserving missing values."""
    return round(value, decimals) if value is not None else None


def _session_duration_minutes(record: dict[str, Any]) -> float | None:
    """Normalize known session duration fields to minutes."""
    duration = _first_key_value(
        record,
        "durationMinute",
        "durationMinutes",
        "chargingDurationMinute",
        "singleChargingTime",
        "durationSeconds",
        "chargingDurationSeconds",
        "duration",
        "chargingDuration",
    )
    if not duration:
        return None
    key, value = duration
    numeric = _float_value(value)
    if numeric is None:
        return None
    if key in {
        "singleChargingTime",
        "durationSeconds",
        "chargingDurationSeconds",
    }:
        return _rounded(numeric / 60)
    return _rounded(numeric)


def _last_session_values(record: dict[str, Any]) -> dict[str, Any]:
    """Return normalized values from the last completed EVDC session record."""
    start_soc = _float_value(
        _first_value(record, "beginningSoc", "startSoc", "startSOC", "beginSoc")
    )
    end_soc = _float_value(_first_value(record, "endSoc", "endSOC", "stopSoc"))
    soc_change = _float_value(_first_value(record, "socChange", "deltaSoc", "socDelta"))
    if soc_change is None and start_soc is not None and end_soc is not None:
        soc_change = end_soc - start_soc

    return {
        "record_id": _first_value(
            record,
            "chargeRecordNumber",
            "recordNumber",
            "id",
            "recordId",
            "sessionId",
        ),
        "start_time": _first_value(
            record,
            "chargingStartTimeStr",
            "startTimeStr",
            "beginTimeStr",
            "chargingStartTime",
            "startTime",
            "beginTime",
        ),
        "end_time": _first_value(
            record,
            "chargingEndTimeStr",
            "endTimeStr",
            "stopTimeStr",
            "chargingEndTime",
            "endTime",
            "stopTime",
        ),
        "duration_minutes": _session_duration_minutes(record),
        "energy_in_kwh": _rounded(
            _float_value(
                _first_value(
                    record,
                    "singleChargingEnergy",
                    "singleChargeEnergy",
                    "singleChargingPower",
                    "chargeEnergy",
                    "chargePower",
                    "chargedEnergy",
                    "chargingEnergy",
                    "energyIn",
                )
            )
        ),
        "energy_out_kwh": _rounded(
            _float_value(
                _first_value(
                    record,
                    "singleDischargeEnergy",
                    "singleDischargingEnergy",
                    "dischargeEnergy",
                    "disChargeEnergy",
                    "dischargedEnergy",
                    "energyOut",
                )
            )
        ),
        "start_soc": start_soc,
        "end_soc": end_soc,
        "soc_change": _rounded(soc_change),
        "end_code": _first_value(record, "chargingEndCode", "endCode", "stopCode"),
        "alarm_code": _first_value(record, "alarmCode", "faultCode", "errorCode"),
        "alarm_name": _first_value(record, "alarmName", "faultName", "errorName"),
        "start_text": _first_value(record, "chargingStartText", "startText"),
        "end_text": _first_value(record, "chargingEndText", "endText", "stopText"),
        "end_reason": _first_value(
            record,
            "endReason",
            "stopReasonName",
            "stopReason",
            "alarmReasonIdName",
        ),
        "end_suggestion": _first_value(record, "endSuggestion", "stopSuggestion"),
    }


class SigenDCChargerOCPPStatusSensor(SigenDCChargerSettingsEntity, SensorEntity):
    """OCPP link status (connected / disconnected / connecting)."""

    _attr_translation_key = "dc_charger_ocpp_link_status"
    _attr_icon = "mdi:lan-connect"

    def __init__(
        self,
        coordinator: SigenSettingsCoordinator,
        station_id: str,
        dc_sn: str,
    ) -> None:
        super().__init__(coordinator, station_id, dc_sn, "dc_charger_ocpp_link_status")

    def _ocpp(self) -> dict[str, Any]:
        if self.coordinator.data is None:
            return {}
        dc_data = (self.coordinator.data.get("dc_chargers") or {}).get(self._dc_sn, {})
        return dc_data.get("ocpp_status") or {}

    @property
    def native_value(self) -> str | None:
        ocpp = self._ocpp()
        if not ocpp:
            return None
        link = ocpp.get("ocppLinkStatus")
        if link is None:
            return None
        return _OCPP_LINK_STATUS_LABELS.get(int(link), f"Status {link}")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        ocpp = self._ocpp()
        if not ocpp:
            return {}
        return {
            "configured_url": ocpp.get("url") or None,
            "available_urls": [
                item.get("value")
                for item in (ocpp.get("urlList") or [])
                if item.get("value")
            ],
        }


class SigenDCChargerLastSessionSensor(SigenDCChargerSettingsEntity, SensorEntity):
    """
    Last completed EVDC charge/discharge session record.

    The HAR captures show the session-history endpoint but not a response body.
    Keep field extraction broad and expose the raw record for schema discovery.
    """

    _attr_translation_key = "dc_charger_last_session"
    _attr_icon = "mdi:clipboard-text-clock"

    def __init__(
        self,
        coordinator: SigenSettingsCoordinator,
        station_id: str,
        dc_sn: str,
    ) -> None:
        super().__init__(coordinator, station_id, dc_sn, "dc_charger_last_session")

    def _last_record(self) -> dict[str, Any] | None:
        if self.coordinator.data is None:
            return None
        dc_data = (self.coordinator.data.get("dc_chargers") or {}).get(self._dc_sn, {})
        records = _session_records(dc_data.get("session_records"))
        return records[0] if records else None

    @property
    def native_value(self) -> str | None:
        record = self._last_record()
        if not record:
            return "No sessions"
        values = _last_session_values(record)
        value = _first_value(
            record,
            "endReason",
            "stopReasonName",
            "stopReason",
            "alarmReasonIdName",
            "statusDesc",
            "statusName",
            "chargeStatusName",
            "chargeModeName",
            "chargingEndText",
            "id",
            "recordId",
        )
        return str(value or values.get("record_id") or "Session")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        record = self._last_record()
        attrs: dict[str, Any] = {
            "description": (
                "Last completed Sigenergy EVDC charge/discharge session record. "
                "Common fields are normalized here and the raw record is included "
                "while the exact cloud payload schema is being mapped."
            ),
            "record_count": 0,
        }
        if not record:
            return attrs
        values = _last_session_values(record)
        attrs.update(
            {
                "record_count": len(
                    _session_records(
                        ((self.coordinator.data or {}).get("dc_chargers") or {})
                        .get(self._dc_sn, {})
                        .get("session_records")
                    )
                ),
                "record_id": values["record_id"],
                "start_time": values["start_time"],
                "end_time": values["end_time"],
                "duration_minutes": values["duration_minutes"],
                "energy_in_kwh": values["energy_in_kwh"],
                "energy_out_kwh": values["energy_out_kwh"],
                "start_soc": values["start_soc"],
                "end_soc": values["end_soc"],
                "soc_change": values["soc_change"],
                "end_code": values["end_code"],
                "alarm_code": values["alarm_code"],
                "alarm_name": values["alarm_name"],
                "start_text": values["start_text"],
                "end_text": values["end_text"],
                "end_reason": values["end_reason"],
                "end_suggestion": values["end_suggestion"],
                "raw_record": record,
            }
        )
        return attrs


class SigenDCChargerLastSessionFieldSensor(SigenDCChargerSettingsEntity, SensorEntity):
    """One recorder-friendly field from the last completed EVDC session record."""

    entity_description: SigenLastSessionFieldDescription

    def __init__(
        self,
        coordinator: SigenSettingsCoordinator,
        station_id: str,
        dc_sn: str,
        description: SigenLastSessionFieldDescription,
    ) -> None:
        super().__init__(coordinator, station_id, dc_sn, description.key)
        self.entity_description = description

    def _last_record(self) -> dict[str, Any] | None:
        if self.coordinator.data is None:
            return None
        dc_data = (self.coordinator.data.get("dc_chargers") or {}).get(self._dc_sn, {})
        records = _session_records(dc_data.get("session_records"))
        return records[0] if records else None

    @property
    def native_value(self) -> str | float | int | None:
        record = self._last_record()
        if not record:
            return None
        return _last_session_values(record).get(self.entity_description.value_key)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        record = self._last_record()
        attrs: dict[str, Any] = {
            "description": self.entity_description.attribute_description,
        }
        if not record:
            return attrs
        values = _last_session_values(record)
        attrs["record_id"] = values["record_id"]
        attrs["end_reason"] = values["end_reason"]
        return attrs


class SigenDCChargerActiveAlarmSensor(SigenDCChargerSettingsEntity, SensorEntity):
    """
    Most-recent active alarm for the DC charger.

    Native value is the alarm name (or "No active alarm"). Code, cause,
    troubleshooting steps, raise/clear times, severity and active count
    surface as attributes.
    """

    _attr_translation_key = "dc_charger_active_alarm"
    _attr_icon = "mdi:alert-circle"

    def __init__(
        self,
        coordinator: SigenSettingsCoordinator,
        station_id: str,
        dc_sn: str,
    ) -> None:
        super().__init__(coordinator, station_id, dc_sn, "dc_charger_active_alarm")

    def _alarms(self) -> list[dict[str, Any]]:
        if self.coordinator.data is None:
            return []
        dc_data = (self.coordinator.data.get("dc_chargers") or {}).get(self._dc_sn, {})
        return dc_data.get("active_alarms") or []

    @property
    def native_value(self) -> str | None:
        alarms = self._alarms()
        if not alarms:
            return "No active alarm"
        return alarms[0].get("alarmName") or alarms[0].get("alarmCode") or "Alarm"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        alarms = self._alarms()
        if not alarms:
            return {"active_count": 0}
        latest = alarms[0]
        return {
            "active_count": len(alarms),
            "alarm_code": latest.get("alarmCode"),
            "sub_code": latest.get("chlidAlarmCode"),
            "alarm_reason": latest.get("alarmReasonIdName"),
            "cause": latest.get("cause"),
            "troubleshooting_steps": latest.get("fixSuggest"),
            "alarm_time": latest.get("alarmTimeStr"),
            "alarm_time_unix": latest.get("alarmTime"),
            "alarm_level": latest.get("alarmLevel"),
            "alarm_id": latest.get("id"),
            "device_sn": latest.get("deviceSnCode"),
        }
