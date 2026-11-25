"""Unit tests for the Sigenergy options flow."""

from __future__ import annotations

import asyncio
import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[1]
COMPONENT = REPO_ROOT / "custom_components" / "sigenergy"


class _Stub:
    """Return a placeholder for any attribute or call."""

    def __init__(self, *args, **kwargs) -> None:
        self.args = args
        self.kwargs = kwargs

    def __getattr__(self, name: str) -> str:
        return name


class _ConfigFlow:
    def __init_subclass__(cls, **kwargs) -> None:
        kwargs.pop("domain", None)
        super().__init_subclass__(**kwargs)


class _OptionsFlow:
    """Mirror current HA: ``config_entry`` is a read-only property."""

    _entry = None

    @property
    def config_entry(self):
        return self._entry

    def async_show_form(self, **kwargs):
        return {"type": "form", **kwargs}

    def async_create_entry(self, **kwargs):
        return {"type": "create_entry", **kwargs}


def _load_config_flow() -> types.ModuleType:
    """Import config_flow.py against minimal stubs, then restore sys.modules."""
    package = types.ModuleType("custom_components.sigenergy")
    package.__path__ = [str(COMPONENT)]
    config_entries = types.ModuleType("homeassistant.config_entries")
    config_entries.ConfigEntry = object
    config_entries.ConfigFlow = _ConfigFlow
    config_entries.ConfigFlowResult = dict
    config_entries.OptionsFlow = _OptionsFlow
    ha_const = types.ModuleType("homeassistant.const")
    ha_const.CONF_PASSWORD = "password"  # noqa: S105
    ha_const.CONF_USERNAME = "username"
    core = types.ModuleType("homeassistant.core")
    core.callback = lambda func: func
    selector = types.ModuleType("homeassistant.helpers.selector")
    selector.SelectSelector = _Stub
    selector.SelectSelectorConfig = _Stub
    selector.TextSelector = _Stub
    selector.TextSelectorConfig = _Stub
    selector.TextSelectorType = _Stub()
    helpers = types.ModuleType("homeassistant.helpers")
    helpers.selector = selector
    homeassistant = types.ModuleType("homeassistant")
    homeassistant.config_entries = config_entries
    voluptuous = types.ModuleType("voluptuous")
    voluptuous.Schema = _Stub
    voluptuous.Optional = _Stub
    voluptuous.Required = lambda key, **kwargs: key
    voluptuous.UNDEFINED = object()
    sigenergy_cloud = types.ModuleType("sigenergy_cloud")
    sigenergy_cloud.SigenergyCloudAuthError = type("AuthError", (Exception,), {})
    sigenergy_cloud.SigenergyCloudClient = _Stub
    sigenergy_cloud.SigenergyCloudError = type("CloudError", (Exception,), {})
    session = types.ModuleType("custom_components.sigenergy.session")
    session.SigenergyCloudSession = _Stub

    stubs = {
        "custom_components": types.ModuleType("custom_components"),
        "custom_components.sigenergy": package,
        "custom_components.sigenergy.session": session,
        "homeassistant": homeassistant,
        "homeassistant.config_entries": config_entries,
        "homeassistant.const": ha_const,
        "homeassistant.core": core,
        "homeassistant.helpers": helpers,
        "homeassistant.helpers.selector": selector,
        "sigenergy_cloud": sigenergy_cloud,
        "voluptuous": voluptuous,
    }
    with mock.patch.dict(sys.modules, stubs):
        for name in ("const", "config_flow"):
            spec = importlib.util.spec_from_file_location(
                f"custom_components.sigenergy.{name}", COMPONENT / f"{name}.py"
            )
            assert spec is not None and spec.loader is not None
            module = importlib.util.module_from_spec(spec)
            sys.modules[spec.name] = module
            spec.loader.exec_module(module)
    return module


config_flow = _load_config_flow()


class OptionsFlowTest(unittest.TestCase):
    """Regression test for issue #37 (options flow 500)."""

    def test_options_flow_works_with_read_only_config_entry(self) -> None:
        entry = types.SimpleNamespace(options={"enabled_modules": ["evdc"]})

        flow = config_flow.SigenConfigFlow.async_get_options_flow(entry)
        # HA sets the flow's handler to the entry ID and config_entry looks the
        # entry up from it; the stub's _entry stands in for that lookup.
        flow._entry = entry
        result = asyncio.run(flow.async_step_init())

        self.assertEqual(result["type"], "form")
        self.assertEqual(result["step_id"], "init")
        (field,) = result["data_schema"].args[0]
        self.assertEqual(field.kwargs["default"], ["evdc"])

        saved = asyncio.run(flow.async_step_init({"enabled_modules": []}))
        self.assertEqual(saved["type"], "create_entry")
        self.assertEqual(saved["data"], {"enabled_modules": []})


if __name__ == "__main__":
    unittest.main()
