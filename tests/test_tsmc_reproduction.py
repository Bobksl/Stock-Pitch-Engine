"""P2.2 — the Phase 2 exit criterion, first half: reproduce, then correct.

Reproduce the TSMC model's published target of TWD 1,732.66 from its own
inputs, then show what the arithmetic error was hiding. Every expected value
below is hand-checked against Audit section 2 and recomputed independently in
Decimal; none is copied out of the implementation.

The three runs differ only in `Conventions`. That is the whole design: one
engine, and a defect is a field of an enumerated record rather than a branch.

    as built        the workbook's own conventions        TWD 1,732.66
    TV corrected    terminal value from the undiscounted
                    final cash flow, nothing else changed TWD 2,359.34
    spec            every convention framework 4 requires  (not asserted --
                    the audit publishes no figure for it)

"Exactly" means to the published cent. Excel computes in binary64 and this
engine in 50-digit Decimal; they agree to roughly 15 significant figures,
which is many orders tighter than a price quoted to two places. Asserting
bit-equality against a float would be asserting something the model never
claimed.
"""
from dataclasses import replace
from decimal import Decimal

import pytest

from src.valuation.dcf import discounted_cash_flow
from src.valuation.inputs import TV_FROM_UNDISCOUNTED_UFCF, Conventions
from src.valuation.money import as_percent, quantize_price

# Audit section 2.2, "As built" row.
PUBLISHED_TARGET = Decimal("1732.66")
AS_BUILT_EV = Decimal("43307.82")
PV_FORECAST = Decimal("7891.38")

# Audit section 2.2, "Corrected" row: the terminal-value double-discount fixed
# and nothing else. TWD billions.
CORRECTED_TARGET = Decimal("2359.34")
CORRECTED_PV_TV = Decimal("51666.26")
CORRECTED_EV = Decimal("59557.64")

# Audit section 2.3 — what the correction reveals.
CORRECTED_TV_SHARE = Decimal("86.75")        # per cent; the audit rounds to 86.8
WACC_LESS_G = Decimal("3.13")                # percentage points, threshold 4

# Audit section 2.3 sensitivity: +/-50bp on g, against the corrected model.
G_DOWN_50BP, TARGET_AT_G_DOWN = Decimal("0.0395"), Decimal("2076.86")
G_UP_50BP, TARGET_AT_G_UP = Decimal("0.0495"), Decimal("2749.11")


@pytest.fixture
def as_built(tsmc_model):
    return discounted_cash_flow(tsmc_model.inputs, tsmc_model.conventions)


@pytest.fixture
def tv_corrected(tsmc_model):
    """The workbook, with only the terminal-value base put right."""
    return discounted_cash_flow(
        tsmc_model.inputs,
        replace(tsmc_model.conventions,
                terminal_value_base=TV_FROM_UNDISCOUNTED_UFCF))


class TestReproduction:
    """If this fails, the parser is wrong, not the model."""

    def test_reproduces_the_published_target(self, as_built):
        assert quantize_price(as_built.share_price) == PUBLISHED_TARGET

    def test_reproduces_the_workbooks_own_cached_result(self, as_built, tsmc_model):
        """Against B27 as Excel computed it, not against a transcription."""
        assert quantize_price(as_built.share_price) == quantize_price(
            tsmc_model.published_price)

    def test_reproduces_the_enterprise_value_bridge(self, as_built):
        assert quantize_price(as_built.pv_forecast) == PV_FORECAST
        assert quantize_price(as_built.enterprise_value) == AS_BUILT_EV

    def test_reproduces_the_wacc(self, as_built):
        """7.5827% on the workbook's own (defective) equity weight."""
        assert as_percent(as_built.wacc, "0.0001") == Decimal("7.5827")


class TestTheCorrection:
    def test_correcting_only_the_terminal_value_moves_the_target(self, tv_corrected):
        assert quantize_price(tv_corrected.share_price) == CORRECTED_TARGET

    def test_the_error_was_one_surplus_discount_factor(self, as_built, tv_corrected):
        """The crispest statement of defect 1.

        TV_as_built = N16*(1+g)/(WACC-g) and N16 = N14 * N15, so the workbook's
        terminal value is numerically identical to the *correct present value*
        of the terminal value -- which it then discounts by N15 a second time.
        """
        assert quantize_price(as_built.terminal_value) == quantize_price(
            tv_corrected.pv_terminal_value) == CORRECTED_PV_TV

    def test_the_corrected_enterprise_value(self, tv_corrected):
        assert quantize_price(tv_corrected.pv_terminal_value) == CORRECTED_PV_TV
        assert quantize_price(tv_corrected.enterprise_value) == CORRECTED_EV

    def test_the_forecast_present_value_is_untouched_by_the_correction(
            self, as_built, tv_corrected):
        assert as_built.pv_forecast == tv_corrected.pv_forecast


class TestWhatTheCorrectionReveals:
    """Audit 2.3: the corrected model is structurally unusable.

    Defects 1 and 2 are the pair that justifies this whole layer -- an
    arithmetic error partially masking a terminal-value-dominated model, the
    two offsetting into a believable number.
    """

    def test_terminal_value_dominates_enterprise_value(self, tv_corrected):
        assert as_percent(tv_corrected.terminal_value_share) == CORRECTED_TV_SHARE
        assert tv_corrected.terminal_value_share > Decimal("0.75")

    def test_the_wacc_minus_g_spread_is_below_four_points(self, tv_corrected):
        assert as_percent(tv_corrected.spread_to_terminal_growth) == WACC_LESS_G
        assert tv_corrected.spread_to_terminal_growth < Decimal("0.04")

    def test_the_as_built_model_hides_neither_condition_by_being_correct(self, as_built):
        """The masking, made explicit: as built, TV share looks unremarkable."""
        assert as_built.terminal_value_share < Decimal("0.85")


class TestSensitivityToTerminalGrowth:
    """Framework 4.6 requires +/-50bp on g reported alongside every DCF."""

    @pytest.mark.parametrize("growth,expected", [
        (G_DOWN_50BP, TARGET_AT_G_DOWN),
        (G_UP_50BP, TARGET_AT_G_UP),
    ])
    def test_fifty_basis_points_on_g(self, tsmc_model, growth, expected):
        result = discounted_cash_flow(
            replace(tsmc_model.inputs, terminal_growth=growth),
            replace(tsmc_model.conventions,
                    terminal_value_base=TV_FROM_UNDISCOUNTED_UFCF))
        assert quantize_price(result.share_price) == expected

    def test_a_hundred_basis_point_band_swings_the_target_by_a_quarter(
            self, tv_corrected):
        """28.5% of the corrected value, on an assumption with no evidence
        behind it. This is what a terminal-value-dominated model means."""
        swing = (TARGET_AT_G_UP - TARGET_AT_G_DOWN) / tv_corrected.share_price
        assert swing > Decimal("0.28")


class TestSpecConventions:
    def test_the_spec_run_differs_from_every_other_run(self, tsmc_model, as_built):
        """No published figure to assert against; assert it is not the others."""
        spec = discounted_cash_flow(tsmc_model.inputs, Conventions.SPEC)
        assert spec.share_price != as_built.share_price
        assert spec.conventions.divergences(Conventions.SPEC) == ()
