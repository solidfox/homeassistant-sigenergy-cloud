"""Custom types for the Sigenergy integration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry

    from .coordinator import SigenEnergyCoordinator, SigenSettingsCoordinator
    from .sigen import Sigen

type SigenConfigEntry = ConfigEntry[SigenData]


@dataclass
class SigenData:
    """Runtime data stored on the config entry."""

    client: Sigen
    energy_coordinator: SigenEnergyCoordinator
    settings_coordinator: SigenSettingsCoordinator
