"""Constants for the Sigenergy integration."""

from logging import Logger, getLogger

LOGGER: Logger = getLogger(__package__)

DOMAIN = "sigenergy"
CONF_REGION = "region"

REGIONS = ["eu", "cn", "apac", "us"]
REGION_LABELS = {
    "eu": "Europe",
    "cn": "China",
    "apac": "Asia-Pacific",
    "us": "United States",
}
