"""Helpers for Sigenergy Nord Pool tax/fee electricity-price settings."""

from __future__ import annotations

from typing import Any

# Sigen stores fee amounts in the station minor currency unit.
# For SEK that unit is öre (conversionRatio=100).
SEK_TO_ORE = 100.0

DIRECTION_BUY = 1
DIRECTION_SELL = 2


def sek_to_ore(value_sek: float) -> float:
    """Convert SEK/kWh to öre/kWh for Sigenergy fee fields."""
    return round(float(value_sek) * SEK_TO_ORE, 4)


def empty_tax_settings(*, fixed_tax_rate: float = 0.0) -> dict[str, Any]:
    """Return a fixed-rate taxSettings block (no TOU tax schedule)."""
    return {
        "enableNegativePriceTax": False,
        "negativePriceTaxRate": 0.0,
        "taxMode": 0,
        "fixedTaxRate": float(fixed_tax_rate),
        "touSchedule": [],
    }


def fixed_fee(
    name: str,
    value_ore: float,
    *,
    apply_tax: bool = True,
    fee_type: int = 0,
) -> dict[str, Any]:
    """Build a fixed additional-fee entry (öre/kWh)."""
    return {
        "feeName": name,
        "feeType": fee_type,
        "applyTax": bool(apply_tax),
        "fixedValue": float(value_ore),
        "touSchedule": [],
    }


def build_buy_tax_and_fee(
    *,
    vat_percent: float,
    energy_tax_sek: float,
    grid_fee_sek: float,
    markup_sek: float,
    energy_tax_name: str = "Energy tax",
    grid_fee_name: str = "Ellevio grid fee",
    markup_name: str = "Supplier markup",
) -> dict[str, Any]:
    """
    Build buy tax/fee so gross ≈ (spot + fees) × (1 + VAT/100).

    All fees use applyTax=true so VAT multiplies spot and adders together,
    matching the Swedish consumer buy formula used in Almis HA.
    """
    return {
        "taxSettings": empty_tax_settings(fixed_tax_rate=float(vat_percent)),
        "additionalFeeList": [
            fixed_fee(energy_tax_name, sek_to_ore(energy_tax_sek), apply_tax=True),
            fixed_fee(grid_fee_name, sek_to_ore(grid_fee_sek), apply_tax=True),
            fixed_fee(markup_name, sek_to_ore(markup_sek), apply_tax=True),
        ],
    }


def build_sell_tax_and_fee(
    *,
    grid_comp_low_sek: float,
    grid_comp_high_sek: float,
    tax_subsidy_sek: float = 0.0,
    fee_name: str = "Ellevio production compensation",
) -> dict[str, Any]:
    """
    Build sell tax/fee: spot + grid compensation (+ optional tax subsidy).

    Ellevio Stockholm microproduction high-load window is modeled as
    Nov–Mar Mon–Fri 06:00–22:00 at ``grid_comp_high_sek``; all other times
    use ``grid_comp_low_sek``. Amounts are converted to öre.
    """
    low = sek_to_ore(grid_comp_low_sek)
    high = sek_to_ore(grid_comp_high_sek)
    fees: list[dict[str, Any]] = [
        {
            "feeName": fee_name,
            "feeType": 1,  # production compensation / credit
            "applyTax": False,
            "fixedValue": 0.0,
            "touSchedule": [
                {
                    "monthRange": "11-03",
                    "weekScheduleList": [
                        {
                            "weekRange": "1-5",
                            "hourScheduleList": [
                                {"hourRange": "00:00-06:00", "value": low},
                                {"hourRange": "06:00-22:00", "value": high},
                                {"hourRange": "22:00-24:00", "value": low},
                            ],
                        },
                        {
                            "weekRange": "6-7",
                            "hourScheduleList": [
                                {"hourRange": "00:00-24:00", "value": low},
                            ],
                        },
                    ],
                },
                {
                    "monthRange": "04-10",
                    "weekScheduleList": [
                        {
                            "weekRange": "1-7",
                            "hourScheduleList": [
                                {"hourRange": "00:00-24:00", "value": low},
                            ],
                        }
                    ],
                },
            ],
        }
    ]
    if tax_subsidy_sek and float(tax_subsidy_sek) > 0:
        fees.append(
            fixed_fee(
                "Production tax subsidy",
                sek_to_ore(tax_subsidy_sek),
                apply_tax=False,
                fee_type=1,
            )
        )
    return {
        "taxSettings": empty_tax_settings(fixed_tax_rate=0.0),
        "additionalFeeList": fees,
    }
