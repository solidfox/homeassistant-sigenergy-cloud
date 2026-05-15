"""Custom types for the Sigenergy integration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from sigenergy_cloud import SigenergyCloudClient

    from .coordinator import SigenSettingsCoordinator, SigenStatusCoordinator

type SigenConfigEntry = ConfigEntry[SigenData]


@dataclass
class SigenData:
    """Runtime data stored on the config entry."""

    client: SigenergyCloudClient
    settings_coordinator: SigenSettingsCoordinator
    status_coordinator: SigenStatusCoordinator
