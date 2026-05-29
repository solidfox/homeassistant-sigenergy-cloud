"""Unit tests for Sigenergy coordinator helpers."""

from __future__ import annotations

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
    update_coordinator = types.ModuleType("homeassistant.helpers.update_coordinator")
    sigenergy_cloud = types.ModuleType("sigenergy_cloud")

    class ConfigEntryAuthFailed(Exception):
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
    update_coordinator.DataUpdateCoordinator = DataUpdateCoordinator
    update_coordinator.UpdateFailed = UpdateFailed
    sigenergy_cloud.SigenergyCloudAuthError = SigenergyCloudAuthError
    sigenergy_cloud.SigenergyCloudError = SigenergyCloudError
    sigenergy_cloud.SigenergyCloudRateLimitError = SigenergyCloudRateLimitError

    sys.modules.setdefault("homeassistant", homeassistant)
    sys.modules.setdefault("homeassistant.exceptions", exceptions)
    sys.modules.setdefault("homeassistant.helpers", helpers)
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
sys.modules["custom_components.sigenergy.const"] = const

spec = importlib.util.spec_from_file_location(
    "custom_components.sigenergy.coordinator",
    REPO_ROOT / "custom_components" / "sigenergy" / "coordinator.py",
)
assert spec is not None and spec.loader is not None
coordinator = importlib.util.module_from_spec(spec)
sys.modules["custom_components.sigenergy.coordinator"] = coordinator
spec.loader.exec_module(coordinator)

_status_dc_data_from_last = coordinator._status_dc_data_from_last


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


if __name__ == "__main__":
    unittest.main()
