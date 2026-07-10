"""Unit tests for Sigenergy coordinator helpers."""

from __future__ import annotations

import asyncio
import sys
import types
import unittest
import importlib.util
from pathlib import Path


def _install_home_assistant_stubs() -> None:
    """Install minimal module stubs so coordinator helpers can be imported."""
    homeassistant = types.ModuleType("homeassistant")
    exceptions = types.ModuleType("homeassistant.exceptions")
    helpers = types.ModuleType("homeassistant.helpers")
    aiohttp_client = types.ModuleType("homeassistant.helpers.aiohttp_client")
    update_coordinator = types.ModuleType("homeassistant.helpers.update_coordinator")
    sigenergy_cloud = types.ModuleType("sigenergy_cloud")

    class ConfigEntryAuthFailed(Exception):
        pass

    class HomeAssistantError(Exception):
        pass

    class DataUpdateCoordinator:
        def __class_getitem__(cls, item):
            return cls

    class UpdateFailed(Exception):
        pass

    class SigenergyCloudAuthError(Exception):
        pass

    class SigenergyCloudError(Exception):
        pass

    class SigenergyCloudRateLimitError(Exception):
        pass

    exceptions.ConfigEntryAuthFailed = ConfigEntryAuthFailed
    exceptions.HomeAssistantError = HomeAssistantError
    update_coordinator.DataUpdateCoordinator = DataUpdateCoordinator
    update_coordinator.UpdateFailed = UpdateFailed
    aiohttp_client.async_get_clientsession = lambda hass: None
    sigenergy_cloud.SigenergyCloudAuthError = SigenergyCloudAuthError
    sigenergy_cloud.SigenergyCloudError = SigenergyCloudError
    sigenergy_cloud.SigenergyCloudRateLimitError = SigenergyCloudRateLimitError

    sys.modules.setdefault("homeassistant", homeassistant)
    sys.modules.setdefault("homeassistant.exceptions", exceptions)
    sys.modules.setdefault("homeassistant.helpers", helpers)
    sys.modules.setdefault("homeassistant.helpers.aiohttp_client", aiohttp_client)
    sys.modules.setdefault(
        "homeassistant.helpers.update_coordinator",
        update_coordinator,
    )
    sys.modules.setdefault("sigenergy_cloud", sigenergy_cloud)


_install_home_assistant_stubs()

REPO_ROOT = Path(__file__).resolve().parents[1]
PACKAGE = types.ModuleType("custom_components.sigenergy")
PACKAGE.__path__ = [str(REPO_ROOT / "custom_components" / "sigenergy")]
sys.modules.setdefault("custom_components", types.ModuleType("custom_components"))
sys.modules["custom_components.sigenergy"] = PACKAGE

const = types.ModuleType("custom_components.sigenergy.const")
const.DOMAIN = "sigenergy"
const.LOGGER = types.SimpleNamespace(warning=lambda *args, **kwargs: None)
const.MODULE_EVDC = "evdc"
const.MODULE_FORECAST = "sigen_ai_forecast"
const.MODULE_STATION_SETTINGS = "station_settings"
const.SIGENERGY_CLOUD_USER_AGENT = "homeassistant-sigenergy/0.1.2"
sys.modules["custom_components.sigenergy.const"] = const

spec = importlib.util.spec_from_file_location(
    "custom_components.sigenergy.coordinator",
    REPO_ROOT / "custom_components" / "sigenergy" / "coordinator.py",
)
assert spec is not None and spec.loader is not None
coordinator = importlib.util.module_from_spec(spec)
sys.modules["custom_components.sigenergy.coordinator"] = coordinator
spec.loader.exec_module(coordinator)

guard_spec = importlib.util.spec_from_file_location(
    "custom_components.sigenergy.evdc_start_guard",
    REPO_ROOT / "custom_components" / "sigenergy" / "evdc_start_guard.py",
)
assert guard_spec is not None and guard_spec.loader is not None
evdc_start_guard = importlib.util.module_from_spec(guard_spec)
sys.modules["custom_components.sigenergy.evdc_start_guard"] = evdc_start_guard
guard_spec.loader.exec_module(evdc_start_guard)

session_spec = importlib.util.spec_from_file_location(
    "custom_components.sigenergy.session",
    REPO_ROOT / "custom_components" / "sigenergy" / "session.py",
)
assert session_spec is not None and session_spec.loader is not None
session_module = importlib.util.module_from_spec(session_spec)
sys.modules["custom_components.sigenergy.session"] = session_module
session_spec.loader.exec_module(session_module)

_status_dc_data_from_last = coordinator._status_dc_data_from_last
_signed_dc_charge_power = coordinator._signed_dc_charge_power
_plug_status_is_plugged_in = coordinator._plug_status_is_plugged_in
_dc_charger_status_is_start_ready = coordinator._dc_charger_status_is_start_ready
_secc_run_state_is_start_ready = coordinator._secc_run_state_is_start_ready
_read_start_readiness = evdc_start_guard._read_start_readiness
_sigenergy_headers = session_module._sigenergy_headers


class _FakeGuardClient:
    """Minimal async client for EVDC start-readiness tests."""

    def __init__(
        self,
        *,
        plug_status=True,
        realtime: dict | None = None,
        charger_status=None,
    ) -> None:
        self.plug_status = plug_status
        self.realtime = realtime or {}
        self.charger_status = charger_status
        self.calls: list[str] = []

    async def dc_plug_status(self, *, dc_sn: str):
        self.calls.append("dc_plug_status")
        return self.plug_status

    async def dc_charge_realtime(self, *, dc_sn: str):
        self.calls.append("dc_charge_realtime")
        return self.realtime

    async def dc_status(self, *, dc_sn: str):
        self.calls.append("dc_status")
        return self.charger_status


class StatusDcDataFromLastTest(unittest.TestCase):
    """Tests for status coordinator last-value seeding."""

    def test_carries_slow_v2x_fields_between_v2x_polls(self) -> None:
        last_dc = {
            "is_charging": False,
            "plugged_in": True,
            "v2x_status": "off",
            "v2x_discharge_enabled": True,
            "v2x_has_car": True,
            "v2x_has_disclaimer": False,
            "v2x_has_used": True,
            "v2x_discharge_settings": {"dischargeEnable": 1},
            "dc_charge_power": -3.2,
        }

        dc_data = _status_dc_data_from_last(
            last_dc,
            station_is_charging=None,
            single_dc=True,
        )

        self.assertIs(dc_data["v2x_discharge_enabled"], True)
        self.assertIs(dc_data["v2x_has_car"], True)
        self.assertIs(dc_data["v2x_has_disclaimer"], False)
        self.assertIs(dc_data["v2x_has_used"], True)
        self.assertEqual(dc_data["v2x_discharge_settings"], {"dischargeEnable": 1})

    def test_single_dc_uses_station_is_charging_hint(self) -> None:
        dc_data = _status_dc_data_from_last(
            {"is_charging": False},
            station_is_charging=True,
            single_dc=True,
        )

        self.assertIs(dc_data["is_charging"], True)

    def test_multiple_dcs_keep_per_charger_last_charging_state(self) -> None:
        dc_data = _status_dc_data_from_last(
            {"is_charging": False},
            station_is_charging=True,
            single_dc=False,
        )

        self.assertIs(dc_data["is_charging"], False)


class SignedDcChargePowerTest(unittest.TestCase):
    """Tests for EVDC signed power convention."""

    def test_positive_power_is_negative_when_secc_is_discharging(self) -> None:
        self.assertEqual(_signed_dc_charge_power(3.2, secc_run_state=8), -3.2)

    def test_positive_power_stays_positive_when_secc_is_charging(self) -> None:
        self.assertEqual(_signed_dc_charge_power(3.2, secc_run_state=3), 3.2)

    def test_negative_power_remains_negative_without_secc_hint(self) -> None:
        self.assertEqual(_signed_dc_charge_power(-3.2, secc_run_state=None), -3.2)


class PlugStatusTest(unittest.TestCase):
    """Tests for EVDC plug-status normalization."""

    def test_string_zero_is_not_plugged_in(self) -> None:
        self.assertIs(_plug_status_is_plugged_in("0"), False)

    def test_plugged_in_label_is_plugged_in(self) -> None:
        self.assertIs(_plug_status_is_plugged_in("Plugged In"), True)

    def test_none_remains_unknown(self) -> None:
        self.assertIsNone(_plug_status_is_plugged_in(None))


class EVDCStartReadinessTest(unittest.TestCase):
    """Tests for EVDC app-status start-readiness normalization."""

    def test_secc_idle_is_start_ready(self) -> None:
        self.assertIs(_secc_run_state_is_start_ready(1), True)

    def test_secc_fault_is_not_start_ready(self) -> None:
        self.assertIs(_secc_run_state_is_start_ready("9"), False)

    def test_status_ready_is_start_ready(self) -> None:
        self.assertIs(_dc_charger_status_is_start_ready("Ready"), True)

    def test_status_plugged_in_is_start_ready(self) -> None:
        self.assertIs(_dc_charger_status_is_start_ready("Plugged In"), True)

    def test_status_establishing_is_not_start_ready(self) -> None:
        self.assertIs(
            _dc_charger_status_is_start_ready("Establishing communication link"),
            False,
        )

    def test_status_charging_fault_is_not_start_ready(self) -> None:
        self.assertIs(_dc_charger_status_is_start_ready("Charging fault"), False)

    def test_status_dict_uses_description(self) -> None:
        self.assertIs(
            _dc_charger_status_is_start_ready({"statusDesc": "Idle"}),
            True,
        )

    def test_status_dict_uses_numeric_status(self) -> None:
        self.assertIs(
            _dc_charger_status_is_start_ready({"status": 1}),
            True,
        )

    def test_guard_skips_realtime_when_unplugged(self) -> None:
        client = _FakeGuardClient(plug_status=False, realtime={"seccRunState": 1})

        readiness = asyncio.run(_read_start_readiness(client, "dc1"))

        self.assertIs(readiness.ready, False)
        self.assertEqual(client.calls, ["dc_plug_status"])

    def test_guard_uses_secc_without_status_fallback_when_decisive(self) -> None:
        client = _FakeGuardClient(
            plug_status=True,
            realtime={"seccRunState": 9},
            charger_status="Ready",
        )

        readiness = asyncio.run(_read_start_readiness(client, "dc1"))

        self.assertIs(readiness.ready, False)
        self.assertEqual(client.calls, ["dc_plug_status", "dc_charge_realtime"])

    def test_guard_accepts_idle_secc_state(self) -> None:
        client = _FakeGuardClient(
            plug_status=True,
            realtime={"seccRunState": 1},
        )

        readiness = asyncio.run(_read_start_readiness(client, "dc1"))

        self.assertIs(readiness.ready, True)
        self.assertEqual(client.calls, ["dc_plug_status", "dc_charge_realtime"])

    def test_guard_falls_back_to_charger_status_when_secc_missing(self) -> None:
        client = _FakeGuardClient(
            plug_status=True,
            realtime={},
            charger_status="Plugged In",
        )

        readiness = asyncio.run(_read_start_readiness(client, "dc1"))

        self.assertIs(readiness.ready, True)
        self.assertEqual(
            client.calls,
            ["dc_plug_status", "dc_charge_realtime", "dc_status"],
        )


class SigenergySessionTest(unittest.TestCase):
    """Tests for Sigenergy Cloud HTTP session request headers."""

    def test_sigenergy_headers_add_user_agent(self) -> None:
        self.assertEqual(
            _sigenergy_headers()["User-Agent"],
            "homeassistant-sigenergy/0.1.2",
        )

    def test_sigenergy_headers_preserve_existing_headers(self) -> None:
        headers = _sigenergy_headers({"Authorization": "Bearer token"})

        self.assertEqual(headers["Authorization"], "Bearer token")
        self.assertEqual(headers["User-Agent"], "homeassistant-sigenergy/0.1.2")


if __name__ == "__main__":
    unittest.main()
