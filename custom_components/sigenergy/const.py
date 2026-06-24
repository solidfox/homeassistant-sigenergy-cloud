"""Constants for the Sigenergy integration."""

from logging import Logger, getLogger
from typing import Any, Mapping

LOGGER: Logger = getLogger(__package__)

DOMAIN = "sigenergy"
CONF_REGION = "region"
CONF_ENABLED_MODULES = "enabled_modules"

REGIONS = ["eu", "cn", "apac", "us"]
REGION_LABELS = {
    "eu": "Europe",
    "cn": "China",
    "apac": "Asia-Pacific",
    "us": "United States",
}

MODULE_STATION_SETTINGS = "station_settings"
MODULE_FORECAST = "sigen_ai_forecast"
MODULE_EVDC = "evdc"
DEFAULT_ENABLED_MODULES = (
    MODULE_STATION_SETTINGS,
    MODULE_FORECAST,
    MODULE_EVDC,
)


def enabled_modules_from_options(options: Mapping[str, Any] | None) -> set[str]:
    """Return enabled cloud fetch modules from config entry options."""
    if options is None or CONF_ENABLED_MODULES not in options:
        return set(DEFAULT_ENABLED_MODULES)

    modules = options.get(CONF_ENABLED_MODULES) or []
    valid_modules = set(DEFAULT_ENABLED_MODULES)
    return {module for module in modules if module in valid_modules}
