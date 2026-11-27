"""Tests for the battery power limit numbers."""

from __future__ import annotations

import asyncio
import importlib.util
import sys
import types
import unittest
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from test_coordinator import REPO_ROOT
from test_rate_limit import (
    _BackoffResetMixin,
    _RecordingSettingsClient,
    _run,
    _settings,
)

UNLIMITED_POWER_KW = 4294967.295
UNLIMITED = f"{UNLIMITED_POWER_KW:.3f}"


def _install_number_stubs() -> None:
    """Add the Home Assistant pieces number.py and entity.py import."""
    number = types.ModuleType("homeassistant.components.number")

    class NumberDeviceClass(StrEnum):
        CURRENT = "current"
        POWER = "power"

    class NumberMode(StrEnum):
        BOX = "box"

    @dataclass(frozen=True, kw_only=True)
    class NumberEntityDescription:
        key: str
        translation_key: str | None = None
        device_class: Any = None
        native_unit_of_measurement: str | None = None
        native_min_value: float | None = None
        native_max_value: float | None = None
        native_step: float | None = None
        mode: Any = None
        icon: str | None = None

    class NumberEntity:
        @property
        def native_max_value(self) -> float:
            return self.entity_description.native_max_value

    number.NumberDeviceClass = NumberDeviceClass
    number.NumberEntity = NumberEntity
    number.NumberEntityDescription = NumberEntityDescription
    number.NumberMode = NumberMode

    ha_const = types.ModuleType("homeassistant.const")
    ha_const.PERCENTAGE = "%"
    ha_const.UnitOfElectricCurrent = types.SimpleNamespace(AMPERE="A")
    ha_const.UnitOfPower = types.SimpleNamespace(KILO_WATT="kW")
    ha_const.UnitOfTime = types.SimpleNamespace(MINUTES="min")

    device_registry = types.ModuleType("homeassistant.helpers.device_registry")
    device_registry.DeviceInfo = dict

    class CoordinatorEntity:
        def __init__(self, coordinator) -> None:
            self.coordinator = coordinator

        def __class_getitem__(cls, item):
            return cls

    sys.modules[
        "homeassistant.helpers.update_coordinator"
    ].CoordinatorEntity = CoordinatorEntity

    def is_unlimited_power(value: Any) -> bool:
        try:
            return float(value) >= UNLIMITED_POWER_KW - 0.001
        except TypeError, ValueError:
            return False

    sigenergy_cloud = sys.modules["sigenergy_cloud"]
    sigenergy_cloud.UNLIMITED_POWER_KW = UNLIMITED_POWER_KW
    sigenergy_cloud.is_unlimited_power = is_unlimited_power
    sigenergy_cloud.BatteryLevelSettings = object
    sigenergy_cloud.PeakShavingSlot = object

    sys.modules.setdefault(
        "homeassistant.components", types.ModuleType("homeassistant.components")
    )
    sys.modules.setdefault("homeassistant.components.number", number)
    sys.modules.setdefault("homeassistant.const", ha_const)
    sys.modules.setdefault("homeassistant.helpers.device_registry", device_registry)


def _load(name: str):
    module_name = f"custom_components.sigenergy.{name}"
    if module_name in sys.modules:
        return sys.modules[module_name]
    spec = importlib.util.spec_from_file_location(
        module_name, REPO_ROOT / "custom_components" / "sigenergy" / f"{name}.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


_install_number_stubs()
_load("entity")
number = _load("number")
HomeAssistantError = sys.modules["homeassistant.exceptions"].HomeAssistantError

CHARGE, DISCHARGE = number.BATTERY_POWER_LIMIT_NUMBERS


class _LimitClient(_RecordingSettingsClient):
    """Settings client that returns a real battery power limit payload."""

    def __init__(self, charge: str, discharge: str) -> None:
        super().__init__()
        self.payload = {
            "batteryMaxChargingPower": charge,
            "batteryMaxDischargingPower": discharge,
        }
        self.writes: list[dict[str, float | None]] = []

    def __getattr__(self, name: str):
        if name == "battery_power_limit":

            async def read():
                self.calls.append(name)
                return dict(self.payload)

            return read
        if name == "set_battery_power_limit":

            async def write(*, max_charge_kw, max_discharge_kw):
                self.calls.append(name)
                self.writes.append(
                    {"charge": max_charge_kw, "discharge": max_discharge_kw}
                )
                return {"code": 0}

            return write
        return super().__getattr__(name)


def _warm(client: _LimitClient):
    """Return a settings coordinator after enough cycles to read every endpoint."""
    settings = _settings(client)
    for _ in range(5):
        settings.data = _run(settings)
    assert "battery_power_limit" in settings._slow_cache
    return settings


def _set(entity, value: float) -> None:
    asyncio.run(entity.async_set_native_value(value))


class BatteryPowerLimitNumberTest(_BackoffResetMixin, unittest.TestCase):
    def test_reads_limit_and_shows_max_for_unlimited(self) -> None:
        settings = _warm(_LimitClient("6.000", UNLIMITED))
        charge = number.SigenBatteryPowerLimitNumber(settings, "1", CHARGE)
        discharge = number.SigenBatteryPowerLimitNumber(settings, "1", DISCHARGE)

        self.assertEqual(charge.native_value, 6.0)
        self.assertFalse(charge.extra_state_attributes["unlimited"])
        self.assertEqual(discharge.native_value, 100.0)
        self.assertTrue(discharge.extra_state_attributes["unlimited"])

    def test_set_keeps_the_other_limit(self) -> None:
        client = _LimitClient("6.000", "4.500")
        settings = _warm(client)
        charge = number.SigenBatteryPowerLimitNumber(settings, "1", CHARGE)

        _set(charge, 3.5)

        self.assertEqual(client.writes, [{"charge": 3.5, "discharge": 4.5}])
        payload = settings.data["battery_power_limit"]
        self.assertEqual(payload["batteryMaxChargingPower"], "3.500")
        self.assertEqual(payload["batteryMaxDischargingPower"], "4.500")

    def test_unlimited_other_limit_is_sent_as_none(self) -> None:
        client = _LimitClient("6.000", UNLIMITED)
        settings = _warm(client)
        charge = number.SigenBatteryPowerLimitNumber(settings, "1", CHARGE)

        _set(charge, 2.0)

        self.assertEqual(client.writes, [{"charge": 2.0, "discharge": None}])

    def test_setting_the_maximum_removes_the_limit(self) -> None:
        client = _LimitClient("6.000", "4.500")
        settings = _warm(client)
        discharge = number.SigenBatteryPowerLimitNumber(settings, "1", DISCHARGE)

        _set(discharge, 100.0)

        self.assertEqual(client.writes, [{"charge": 6.0, "discharge": None}])
        payload = settings.data["battery_power_limit"]
        self.assertEqual(payload["batteryMaxDischargingPower"], UNLIMITED)
        self.assertTrue(discharge.extra_state_attributes["unlimited"])

    def test_no_write_when_the_limits_cannot_be_read(self) -> None:
        client = _LimitClient("6.000", "4.500")
        client.payload = {"batteryMaxChargingPower": "6.000"}
        settings = _settings(client)
        settings.data = {}
        charge = number.SigenBatteryPowerLimitNumber(settings, "1", CHARGE)

        with self.assertRaises(HomeAssistantError):
            _set(charge, 3.0)
        self.assertEqual(client.writes, [])

    def test_set_keeps_an_other_limit_changed_since_the_last_poll(self) -> None:
        client = _LimitClient("6.000", "4.500")
        settings = _warm(client)
        charge = number.SigenBatteryPowerLimitNumber(settings, "1", CHARGE)
        discharge = number.SigenBatteryPowerLimitNumber(settings, "1", DISCHARGE)
        # Changed in the app; the hourly cache still holds 4.5.
        client.payload["batteryMaxDischargingPower"] = "0.000"

        _set(charge, 3.0)

        self.assertEqual(client.writes, [{"charge": 3.0, "discharge": 0.0}])
        self.assertEqual(discharge.native_value, 0.0)

    def test_no_write_when_the_other_limit_is_unreadable(self) -> None:
        client = _LimitClient("6.000", "")
        settings = _warm(client)
        charge = number.SigenBatteryPowerLimitNumber(settings, "1", CHARGE)

        with self.assertRaises(HomeAssistantError):
            _set(charge, 3.0)
        self.assertEqual(client.writes, [])

    def test_written_value_survives_the_next_poll(self) -> None:
        client = _LimitClient("6.000", UNLIMITED)
        settings = _warm(client)
        charge = number.SigenBatteryPowerLimitNumber(settings, "1", CHARGE)
        _set(charge, 3.0)
        client.calls.clear()

        # The endpoint is slow-cached for an hour, so the next poll serves the
        # cache. It must hold the written value, not the pre-write one.
        settings.data = _run(settings)

        self.assertNotIn("battery_power_limit", client.calls)
        self.assertEqual(charge.native_value, 3.0)


class UpdateCachedDataTest(_BackoffResetMixin, unittest.TestCase):
    def test_local_update_alone_is_undone_by_the_slow_cache(self) -> None:
        settings = _warm(_LimitClient("6.000", UNLIMITED))
        settings.async_update_local_data(
            {"battery_power_limit": {"batteryMaxChargingPower": "1.000"}}
        )

        data = _run(settings)

        self.assertEqual(
            data["battery_power_limit"]["batteryMaxChargingPower"], "6.000"
        )

    def test_cached_update_is_kept_and_marked_fresh(self) -> None:
        settings = _warm(_LimitClient("6.000", UNLIMITED))
        settings._slow_cache_updated_at.pop("battery_power_limit")

        settings.async_update_cached_data(
            "battery_power_limit", {"batteryMaxChargingPower": "1.000"}
        )
        data = _run(settings)

        self.assertIn("battery_power_limit", settings._slow_cache_updated_at)
        self.assertEqual(
            data["battery_power_limit"]["batteryMaxChargingPower"], "1.000"
        )


if __name__ == "__main__":
    unittest.main()
