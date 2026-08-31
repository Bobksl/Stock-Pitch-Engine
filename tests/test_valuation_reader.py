"""P2.2 — reading a foreign workbook: its inputs, and the conventions it implements.

Every expected value is read off tests/fixtures/tsmc_model.xlsx by hand. The
convention assertions are the interesting ones: they are derived from the
*formulas*, and they are how three defects that leave no trace in any value
become visible at all.
"""
from dataclasses import replace
from decimal import Decimal

import pytest

from src.valuation.inputs import (
    EQUITY_WEIGHT_MARKET_CAP_LESS_DEBT,
    STUB_FULL_YEAR_AT_STUB_FACTOR,
    TV_FROM_DISCOUNTED_UFCF,
    Conventions,
)
from src.valuation.money import D
from src.valuation.excel.reader import TSMC_CELL_MAP, WorkbookError, read_model


class TestDeclaredInputs:
    def test_cost_of_capital_inputs(self, tsmc_model):
        i = tsmc_model.inputs
        assert i.beta == Decimal("1.22")
        assert i.risk_free_rate == Decimal("0.0138")
        assert i.equity_risk_premium == Decimal("0.0518")
        assert i.cost_of_debt == Decimal("0.04192")
        assert i.tax_rate == Decimal("0.166")
        assert i.terminal_growth == Decimal("0.0445")

    def test_capital_structure_is_scaled_to_the_forecast_unit(self, tsmc_model):
        """B5/B6 are stated in trillions; the forecast is in billions.

        Scale is read from the declared cell map, never inferred (6.4).
        """
        i = tsmc_model.inputs
        assert i.unit == "billion"
        assert i.market_capitalisation == Decimal("36310.00")   # 36.31 trillion
        assert i.gross_debt == Decimal("1010.00")               # 1.01 trillion

    def test_market_cap_is_read_through_the_formula_that_buries_it(self, tsmc_model):
        """B6 is '=36.31-B5'. The literal is the market cap; the subtraction
        is a convention, and a defective one."""
        assert tsmc_model.inputs.market_capitalisation == Decimal("36310.00")

    def test_equity_bridge(self, tsmc_model):
        i = tsmc_model.inputs
        assert i.total_debt == Decimal("-1010")
        assert i.cash_and_equivalents == Decimal("2630")
        assert i.shares_outstanding == Decimal("25.93")

    def test_forecast_spans_six_periods_from_the_last_actual(self, tsmc_model):
        i = tsmc_model.inputs
        assert i.base_period == 2024
        assert i.base_revenue == Decimal("2894.3077")
        assert [f.period for f in i.forecast] == [2025, 2026, 2027, 2028, 2029, 2030]
        assert i.horizon == 6

    def test_first_and_last_forecast_drivers(self, tsmc_model):
        first, last = tsmc_model.inputs.forecast[0], tsmc_model.inputs.forecast[-1]
        assert first.revenue_growth == Decimal("0.368")
        assert first.ebitda_margin == Decimal("0.6733")
        assert first.depreciation == Decimal("791.9")
        assert first.capex == Decimal("-1187.9")
        assert first.change_in_nwc == Decimal("-53.3")
        assert last.revenue_growth == Decimal("0.115")
        assert last.ebitda_margin == Decimal("0.6879")
        assert last.capex == Decimal("-2134.46")

    def test_gross_margin_is_carried_although_the_ufcf_never_uses_it(self, tsmc_model):
        """The dead line of defect 8. Read it, so the audit can say it is dead."""
        assert tsmc_model.inputs.forecast[0].gross_margin == Decimal("0.5601")

    def test_a_foreign_workbook_declares_no_provenance(self, tsmc_model):
        """The absence is the finding: defects 4 and 5 live here."""
        assert tsmc_model.inputs.provenance == {}
        assert tsmc_model.inputs.undeclared(("beta", "terminal_growth")) == (
            "beta", "terminal_growth")

    def test_published_price_is_read_for_the_reproduction_assertion(self, tsmc_model):
        assert tsmc_model.published_price == Decimal("1732.6580946600232")


class TestConventionsReadFromFormulas:
    def test_stub_fraction_comes_from_the_discount_factor_exponent(self, tsmc_model):
        """I15 is '=1/POWER(1+B13,1/6)': two months of a year remaining."""
        assert tsmc_model.inputs.stub_fraction == D(1) / D(6)

    def test_terminal_value_is_built_from_the_discounted_cash_flow(self, tsmc_model):
        """B18 is '=N16*(1+B17)/(B13-B17)'. N16 is discounted; N14 is not.

        Defect 1, and invisible in every value the workbook displays.
        """
        assert tsmc_model.conventions.terminal_value_base == TV_FROM_DISCOUNTED_UFCF

    def test_equity_weight_nets_debt_out_of_market_cap(self, tsmc_model):
        """B6 is '=36.31-B5'. Defect 6."""
        assert (tsmc_model.conventions.equity_weight_basis
                == EQUITY_WEIGHT_MARKET_CAP_LESS_DEBT)

    def test_a_full_year_of_cash_flow_is_discounted_at_the_stub_factor(self, tsmc_model):
        """I16 is '=I14*I15': all of 2025's UFCF, two months of discounting.

        Defect 7.
        """
        assert tsmc_model.conventions.stub_policy == STUB_FULL_YEAR_AT_STUB_FACTOR

    def test_all_three_diverge_from_spec(self, tsmc_model):
        """The defect list is a diff, not a hand-maintained catalogue."""
        assert tsmc_model.conventions.divergences(Conventions.SPEC) == (
            "terminal_value_base", "equity_weight_basis", "stub_policy")

    def test_spec_conventions_do_not_diverge_from_themselves(self):
        assert Conventions.SPEC.divergences(Conventions.SPEC) == ()


class TestReaderFailsLoudly:
    def test_a_cell_map_pointing_at_the_wrong_sheet_raises(self, tsmc_workbook):
        with pytest.raises(Exception):
            read_model(tsmc_workbook, replace(TSMC_CELL_MAP, sheet="Nope"))

    def test_a_terminal_value_referencing_neither_row_raises(self, tsmc_workbook):
        """B25 is the equity-value sum; it names neither UFCF row."""
        with pytest.raises(WorkbookError, match="references neither"):
            read_model(tsmc_workbook, replace(TSMC_CELL_MAP, cell_terminal_value="B25"))
