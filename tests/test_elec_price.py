"""Unit tests for Nord Pool tax/fee payload builders."""

from custom_components.sigenergy.elec_price import (
    build_buy_tax_and_fee,
    build_sell_tax_and_fee,
    sek_to_ore,
)


def test_sek_to_ore() -> None:
    assert sek_to_ore(0.36) == 36.0
    assert sek_to_ore(0.09316) == 9.316
    assert sek_to_ore(0.0412) == 4.12


def test_build_buy_tax_and_fee_matches_swedish_gross_model() -> None:
    payload = build_buy_tax_and_fee(
        vat_percent=25.0,
        energy_tax_sek=0.36,
        grid_fee_sek=0.208,
        markup_sek=0.09316,
    )
    assert payload["taxSettings"]["fixedTaxRate"] == 25.0
    fees = payload["additionalFeeList"]
    assert len(fees) == 3
    assert all(fee["applyTax"] is True for fee in fees)
    total_ore = sum(fee["fixedValue"] for fee in fees)
    assert abs(total_ore - 66.116) < 1e-6
    # Gross intercept b = fees_ore/100 * 1.25
    b_sek = total_ore / 100.0 * 1.25
    assert abs(b_sek - 0.82645) < 1e-6


def test_build_sell_tax_and_fee_tou() -> None:
    payload = build_sell_tax_and_fee(
        grid_comp_low_sek=0.0412,
        grid_comp_high_sek=0.055,
        tax_subsidy_sek=0.0,
    )
    assert payload["taxSettings"]["fixedTaxRate"] == 0.0
    fee = payload["additionalFeeList"][0]
    assert fee["feeType"] == 1
    assert len(fee["touSchedule"]) == 2
    high_season = fee["touSchedule"][0]
    assert high_season["monthRange"] == "11-03"
    weekday_hours = high_season["weekScheduleList"][0]["hourScheduleList"]
    assert weekday_hours[1] == {"hourRange": "06:00-22:00", "value": 5.5}


def test_build_sell_includes_tax_subsidy_when_positive() -> None:
    payload = build_sell_tax_and_fee(
        grid_comp_low_sek=0.0412,
        grid_comp_high_sek=0.055,
        tax_subsidy_sek=0.60,
    )
    assert len(payload["additionalFeeList"]) == 2
    assert payload["additionalFeeList"][1]["fixedValue"] == 60.0
