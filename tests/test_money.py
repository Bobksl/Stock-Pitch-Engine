"""P2.2 — the Decimal boundary holds.

The point of these tests is not that Decimal arithmetic works. It is that the
one way a float can reach a financial figure is the one door named for it, and
that the door recovers the literal a modeller typed rather than its binary
expansion. Every expected value below is hand-checked.
"""
from decimal import Decimal

import pytest

from src.valuation.money import (
    D,
    PrecisionError,
    as_percent,
    divide,
    from_spreadsheet,
    power,
    quantize_price,
)


class TestTheFloatBoundary:
    def test_D_refuses_a_float(self):
        with pytest.raises(PrecisionError) as exc:
            D(1.22)
        # The message must name the fix, not merely the sin.
        assert "from_spreadsheet" in str(exc.value)

    def test_D_refuses_a_bool_which_is_an_int_in_disguise(self):
        with pytest.raises(PrecisionError):
            D(True)

    def test_D_accepts_str_int_and_Decimal(self):
        assert D("0.0445") == Decimal("0.0445")
        assert D(2630) == Decimal(2630)
        assert D(Decimal("1.22")) == Decimal("1.22")

    def test_the_rejected_float_really_was_inexact(self):
        """The reason for the rule, stated as a test rather than a comment."""
        assert Decimal(1.22) != Decimal("1.22")
        assert str(Decimal(1.22)).startswith("1.2199999999")


class TestFromSpreadsheet:
    def test_recovers_the_typed_literal_not_the_binary_expansion(self):
        assert from_spreadsheet(1.22) == Decimal("1.22")
        assert from_spreadsheet(2894.3077) == Decimal("2894.3077")
        assert from_spreadsheet(-1187.9) == Decimal("-1187.9")
        assert from_spreadsheet(0.6733) == Decimal("0.6733")

    def test_integers_and_decimals_pass_through(self):
        assert from_spreadsheet(2630) == Decimal(2630)
        assert from_spreadsheet(Decimal("25.93")) == Decimal("25.93")

    def test_rejects_non_finite_and_non_numeric(self):
        for bad in (float("nan"), float("inf"), True, None, [1]):
            with pytest.raises(PrecisionError):
                from_spreadsheet(bad)


class TestArithmetic:
    def test_fractional_powers_are_exact_enough_for_a_stub_factor(self):
        """(1+WACC)^(1/6) at TSMC's WACC, hand-checked to 15 places."""
        base = Decimal("1.075826761024511153952079316992564031947122004957311")
        got = power(base, D(1) / D(6))
        assert str(got).startswith("1.012256071903862")

    def test_a_full_period_factor_is_the_base_itself(self):
        assert power(Decimal("1.05"), D(1)) == Decimal("1.05")

    def test_divide_names_a_collapsed_denominator(self):
        with pytest.raises(ZeroDivisionError):
            divide(D(1), D(0))

    def test_division_is_not_truncated_at_default_precision(self):
        # 1/6 to 50 significant digits, not 28.
        assert len(str(divide(D(1), D(6))).split(".")[1]) >= 45


class TestPresentation:
    def test_quantize_price_rounds_half_up_to_the_cent(self):
        assert quantize_price(Decimal("1732.6580946600232")) == Decimal("1732.66")
        assert quantize_price(Decimal("2359.3383724959129")) == Decimal("2359.34")
        assert quantize_price(Decimal("0.005")) == Decimal("0.01")

    def test_as_percent_expresses_a_rate_in_points(self):
        assert as_percent(Decimal("0.031326761024511153")) == Decimal("3.13")
        assert as_percent(Decimal("0.8675001069948348")) == Decimal("86.75")
