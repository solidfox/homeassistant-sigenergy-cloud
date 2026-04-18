"""Electricity tariff and price configuration endpoints.

Two separate systems are in play:

1. stationelecsetprice — static/manual electricity price settings.
   Used when the user enters fixed buy/sell prices rather than a live feed.

2. prediction/aipv/elecPrice — AI-mode tariff configuration.
   Supports dynamic spot prices, TOU schedules, tax settings, and
   additional fees (e.g. grid operator fees). This is the richer system
   and the one used for AI-mode optimisation.

3. data-process tariff-soc — read-only historical tariff+SOC time-series
   (charting data, not configuration).

Known endpoints:

Static pricing:
    GET /device/stationelecsetprice/latest/price?stationId={sid}
    GET /device/stationelecsetprice/latest/static/price?stationId={sid}
    GET /device/stationelecsetprice/getCountryCurrency?stationId={sid}
    GET /device/stationelecsetprice/demand-pricing/supported?stationId={sid}

AI tariff:
    GET /prediction/aipv/elecPrice/get/tariffDetail/{stationId}?supportAgl=1
    GET /prediction/aipv/elecPrice/get/priceCost?stationId={sid}
    GET /prediction/aipv/elecPrice/popup?stationId={sid}
    PUT /prediction/aipv/elecPrice/save/directionCost
        body: {
            "stationId": int,
            "direction": int,         # 0=buy, 1=sell, 2=both (unverified)
            "priceCoefficient": float|null,
            "priceCost": float|null,
            "taxSettings": {
                "enableNegativePriceTax": bool,
                "negativePriceTaxRate": float|null,
                "taxMode": int,       # 0=fixed (unverified)
                "fixedTaxRate": float,
                "touSchedule": []     # TOU-based tax rates (shape TBD)
            },
            "additionalFeeList": [
                {
                    "feeName": str,
                    "feeType": int,   # 0=fixed (unverified)
                    "applyTax": bool,
                    "fixedValue": float,
                    "touSchedule": [] # TOU-based fee schedule (shape TBD)
                }
            ]
        }

Historical (read-only):
    GET /data-process/sigen/station/statistics/tariff-soc/day
        ?stationId={sid}&dt={YYYYMMDD}&needPrediction={bool}
        Response: time-series of BUY_TARIFF and SOC values at 5-min intervals.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date

import aiohttp

from .auth import TokenManager

logger = logging.getLogger(__name__)


@dataclass
class TaxSettings:
    """Tax configuration applied to electricity prices.

    Attributes:
        tax_mode:                  0 = fixed rate (other modes TBD).
        fixed_tax_rate:            Tax rate as a fraction (e.g. 0.25 = 25%).
        enable_negative_price_tax: Whether tax applies when spot price is negative.
        negative_price_tax_rate:   Tax rate for negative prices (if different).
        tou_schedule:              Time-of-use tax rates (shape TBD from capture).
    """

    tax_mode: int = 0
    fixed_tax_rate: float = 0.0
    enable_negative_price_tax: bool = False
    negative_price_tax_rate: float | None = None
    tou_schedule: list = field(default_factory=list)

    @classmethod
    def from_api(cls, data: dict) -> "TaxSettings":
        return cls(
            tax_mode=data.get("taxMode", 0),
            fixed_tax_rate=float(data.get("fixedTaxRate", 0)),
            enable_negative_price_tax=data.get("enableNegativePriceTax", False),
            negative_price_tax_rate=data.get("negativePriceTaxRate"),
            tou_schedule=data.get("touSchedule", []),
        )

    def to_api(self) -> dict:
        return {
            "taxMode": self.tax_mode,
            "fixedTaxRate": self.fixed_tax_rate,
            "enableNegativePriceTax": self.enable_negative_price_tax,
            "negativePriceTaxRate": self.negative_price_tax_rate,
            "touSchedule": self.tou_schedule,
        }


@dataclass
class AdditionalFee:
    """An additional fixed or TOU-based electricity fee (e.g. grid operator fee).

    Example: Ellevio Produktionsersättning (Swedish grid production compensation).

    Attributes:
        fee_name:     Display name of the fee.
        fee_type:     0 = fixed value (other types TBD).
        fixed_value:  Fee amount in the station's currency unit (e.g. SEK/kWh).
        apply_tax:    Whether the configured tax rate applies to this fee.
        tou_schedule: TOU-based fee schedule (shape TBD from capture).
    """

    fee_name: str
    fee_type: int = 0
    fixed_value: float = 0.0
    apply_tax: bool = False
    tou_schedule: list = field(default_factory=list)

    @classmethod
    def from_api(cls, data: dict) -> "AdditionalFee":
        return cls(
            fee_name=data["feeName"],
            fee_type=data.get("feeType", 0),
            fixed_value=float(data.get("fixedValue", 0)),
            apply_tax=data.get("applyTax", False),
            tou_schedule=data.get("touSchedule", []),
        )

    def to_api(self) -> dict:
        return {
            "feeName": self.fee_name,
            "feeType": self.fee_type,
            "fixedValue": self.fixed_value,
            "applyTax": self.apply_tax,
            "touSchedule": self.tou_schedule,
        }


@dataclass
class DirectionCostSettings:
    """Buy/sell price configuration for AI-mode tariff optimisation.

    Attributes:
        direction:          Which direction this applies to.
                            Observed value: 2. Likely 0=buy, 1=sell, 2=both.
        price_coefficient:  Multiplier applied to spot price (null = none).
        price_cost:         Fixed price override in currency/kWh (null = use spot).
        tax_settings:       Tax configuration.
        additional_fees:    List of additional fees (e.g. grid operator charges).
    """

    direction: int = 2
    price_coefficient: float | None = None
    price_cost: float | None = None
    tax_settings: TaxSettings = field(default_factory=TaxSettings)
    additional_fees: list[AdditionalFee] = field(default_factory=list)

    @classmethod
    def from_api(cls, data: dict) -> "DirectionCostSettings":
        return cls(
            direction=data.get("direction", 2),
            price_coefficient=data.get("priceCoefficient"),
            price_cost=data.get("priceCost"),
            tax_settings=TaxSettings.from_api(data.get("taxSettings", {})),
            additional_fees=[
                AdditionalFee.from_api(f) for f in data.get("additionalFeeList", [])
            ],
        )

    def to_api(self, station_id: int) -> dict:
        return {
            "stationId": station_id,
            "direction": self.direction,
            "priceCoefficient": self.price_coefficient,
            "priceCost": self.price_cost,
            "taxSettings": self.tax_settings.to_api(),
            "additionalFeeList": [f.to_api() for f in self.additional_fees],
        }


# ── Static pricing ────────────────────────────────────────────────────────────

async def get_latest_price(
    base_url: str, token_mgr: TokenManager, station_id: str
) -> dict:
    """Get the current electricity price settings (static/manual).

    GET {base}/device/stationelecsetprice/latest/price?stationId={station_id}
    """
    await token_mgr.ensure_valid_token(base_url)
    url = f"{base_url}device/stationelecsetprice/latest/price"
    async with aiohttp.ClientSession() as session:
        async with session.get(
            url, headers=token_mgr.headers, params={"stationId": station_id}
        ) as response:
            return (await response.json())["data"]


async def get_static_price(
    base_url: str, token_mgr: TokenManager, station_id: str
) -> dict:
    """Get the static electricity price configuration.

    GET {base}/device/stationelecsetprice/latest/static/price?stationId={station_id}
    """
    await token_mgr.ensure_valid_token(base_url)
    url = f"{base_url}device/stationelecsetprice/latest/static/price"
    async with aiohttp.ClientSession() as session:
        async with session.get(
            url, headers=token_mgr.headers, params={"stationId": station_id}
        ) as response:
            return (await response.json())["data"]


async def get_country_currency(
    base_url: str, token_mgr: TokenManager, station_id: str
) -> dict:
    """Get the country and currency for this station.

    GET {base}/device/stationelecsetprice/getCountryCurrency?stationId={station_id}
    """
    await token_mgr.ensure_valid_token(base_url)
    url = f"{base_url}device/stationelecsetprice/getCountryCurrency"
    async with aiohttp.ClientSession() as session:
        async with session.get(
            url, headers=token_mgr.headers, params={"stationId": station_id}
        ) as response:
            return (await response.json())["data"]


async def get_demand_pricing_supported(
    base_url: str, token_mgr: TokenManager, station_id: str
) -> dict:
    """Check whether demand pricing is supported for this station.

    GET {base}/device/stationelecsetprice/demand-pricing/supported?stationId={station_id}
    """
    await token_mgr.ensure_valid_token(base_url)
    url = f"{base_url}device/stationelecsetprice/demand-pricing/supported"
    async with aiohttp.ClientSession() as session:
        async with session.get(
            url, headers=token_mgr.headers, params={"stationId": station_id}
        ) as response:
            return (await response.json())["data"]


# ── AI tariff ─────────────────────────────────────────────────────────────────

async def get_tariff_detail(
    base_url: str, token_mgr: TokenManager, station_id: str
) -> dict:
    """Get the full tariff configuration used by AI mode.

    Includes buy/sell prices, TOU schedule, and provider details.

    GET {base}/prediction/aipv/elecPrice/get/tariffDetail/{station_id}?supportAgl=1
    """
    await token_mgr.ensure_valid_token(base_url)
    url = f"{base_url}prediction/aipv/elecPrice/get/tariffDetail/{station_id}"
    async with aiohttp.ClientSession() as session:
        async with session.get(
            url, headers=token_mgr.headers, params={"supportAgl": 1}
        ) as response:
            return (await response.json())["data"]


async def get_price_cost(
    base_url: str, token_mgr: TokenManager, station_id: str
) -> dict:
    """Get the current direction cost / price-cost settings for AI mode.

    GET {base}/prediction/aipv/elecPrice/get/priceCost?stationId={station_id}
    """
    await token_mgr.ensure_valid_token(base_url)
    url = f"{base_url}prediction/aipv/elecPrice/get/priceCost"
    async with aiohttp.ClientSession() as session:
        async with session.get(
            url, headers=token_mgr.headers, params={"stationId": station_id}
        ) as response:
            return (await response.json())["data"]


async def save_direction_cost(
    base_url: str,
    token_mgr: TokenManager,
    station_id: str,
    settings: DirectionCostSettings,
) -> dict:
    """Save buy/sell price configuration for AI-mode tariff optimisation.

    This controls how the AI mode values grid import/export — including
    spot price adjustments, tax settings, and additional grid fees.

    PUT {base}/prediction/aipv/elecPrice/save/directionCost
    """
    await token_mgr.ensure_valid_token(base_url)
    url = f"{base_url}prediction/aipv/elecPrice/save/directionCost"
    async with aiohttp.ClientSession() as session:
        async with session.put(
            url, headers=token_mgr.headers, json=settings.to_api(int(station_id))
        ) as response:
            return await response.json()


# ── Historical tariff data (read-only) ───────────────────────────────────────

async def get_tariff_soc_history(
    base_url: str,
    token_mgr: TokenManager,
    station_id: str,
    day: date,
    include_prediction: bool = False,
) -> dict:
    """Get a day's worth of tariff and SOC time-series data (5-min intervals).

    Returns BUY_TARIFF (and possibly SELL_TARIFF/SOC) series, useful for
    charting or understanding what prices the system saw on a given day.

    GET {base}/data-process/sigen/station/statistics/tariff-soc/day
        ?stationId={station_id}&dt={YYYYMMDD}&needPrediction={bool}
    """
    await token_mgr.ensure_valid_token(base_url)
    url = f"{base_url}data-process/sigen/station/statistics/tariff-soc/day"
    params = {
        "stationId": station_id,
        "dt": day.strftime("%Y%m%d"),
        "needPrediction": str(include_prediction).lower(),
    }
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=token_mgr.headers, params=params) as response:
            return (await response.json())["data"]
