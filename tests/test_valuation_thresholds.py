"""P2.8 — defects 2 and 3, and the first Class B findings a real model raises.

These are the rules an exception can satisfy, and the tests below are as much
about that boundary as about the thresholds: a declared exception moves a
Class B finding out of `blocking` and into a published disclosure, and does
nothing whatsoever to the five Class A findings sitting beside it.
"""
from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest

from src.qc.rules import CLASS_B, DEFECTS
from src.qc.valuation_rules import (
    TERMINAL_VALUE_SHARE_LIMIT,
    WACC_GROWTH_SPREAD_FLOOR,
    terminal_value_share_finding,
    threshold_findings,
    wacc_growth_spread_finding,
)
from src.valuation.dcf import discounted_cash_flow, terminal_growth_sensitivity
from src.valuation.excel.audit import audit_workbook
from src.valuation.inputs import Conventions
from src.valuation.money import as_percent, quantize_price

TODAY = date(2026, 9, 1)

TV_SHARE_EXCEPTION = """
tsmc_tv_share:
  condition: terminal_value_share
  measured: 0.8675
  reason: long_duration_asset
  detail: TV share 86.8%, above the 75% threshold
  author: Bob Liang
  date: 2026-08-31
  expiry: 2027-02-28
"""


@pytest.fixture(scope="module")
def audit(request):
    workbook = request.path.parent / "fixtures" / "tsmc_model.xlsx"
    return audit_workbook(workbook, published_price_cell="B27", externals={},
                          as_of=TODAY)


class TestDefectTwoTerminalValueShare:
    def test_it_fires_on_the_corrected_model(self, audit):
        finding = terminal_value_share_finding(audit.tv_corrected)
        assert finding is not None
        assert finding.rule.id == DEFECTS[2]
        assert finding.rule.rule_class == CLASS_B
        assert finding.threshold == TERMINAL_VALUE_SHARE_LIMIT
        assert as_percent(finding.measured) == Decimal("86.75")

    def test_it_also_fires_on_the_model_as_published(self, audit):
        """81.78% is already above 75%.

        The arithmetic error understated the dominance rather than concealing
        the breach. Stating this precisely matters: the framework catches this
        model without correcting anything first.
        """
        assert as_percent(audit.as_built.terminal_value_share) == Decimal("81.78")
        assert terminal_value_share_finding(audit.as_built) is not None

    def test_the_detail_names_both_readings(self, audit):
        finding = terminal_value_share_finding(audit.tv_corrected, audit.as_built)
        assert "86.75%" in finding.detail and "81.78%" in finding.detail
        assert "understated the dominance" in finding.detail

    def test_the_detail_carries_the_sensitivity_band(self, audit):
        finding = terminal_value_share_finding(
            audit.tv_corrected, audit.as_built, audit.sensitivity)
        assert "TWD 2,076.86 to TWD 2,749.11" in finding.detail
        assert "28.49%" in finding.detail

    def test_a_model_below_the_threshold_raises_nothing(self, audit):
        """Terminal growth has to reach zero before the rule stops firing."""
        modest = discounted_cash_flow(
            replace(audit.model.inputs, terminal_growth=Decimal("0")),
            audit.tv_corrected.conventions)
        assert modest.terminal_value_share < TERMINAL_VALUE_SHARE_LIMIT
        assert terminal_value_share_finding(modest) is None

    def test_how_far_g_must_fall_before_the_rule_clears(self, audit):
        """A measure of how dominated this model is, and it is startling.

        At g = 1% -- less than a quarter of the 4.45% assumed, and far below
        any plausible long-run nominal rate -- terminal value is still 75.08%
        of enterprise value. There is no reasonable growth assumption under
        which this DCF is carried by its explicit forecast.
        """
        at_one_percent = discounted_cash_flow(
            replace(audit.model.inputs, terminal_growth=Decimal("0.01")),
            audit.tv_corrected.conventions)
        assert as_percent(at_one_percent.terminal_value_share) == Decimal("75.08")
        assert terminal_value_share_finding(at_one_percent) is not None


class TestDefectThreeSpread:
    def test_it_fires_on_a_thin_spread(self, audit):
        finding = wacc_growth_spread_finding(audit.tv_corrected)
        assert finding is not None
        assert finding.rule.id == DEFECTS[3]
        assert finding.rule.rule_class == CLASS_B
        assert as_percent(finding.measured) == Decimal("3.13")
        assert finding.threshold == WACC_GROWTH_SPREAD_FLOOR

    def test_the_detail_names_both_sides_of_the_subtraction(self, audit):
        detail = wacc_growth_spread_finding(audit.tv_corrected).detail
        assert "7.5827%" in detail and "4.45%" in detail
        assert "wearing a DCF as a disguise" in detail

    def test_a_wide_spread_raises_nothing(self, audit):
        wide = discounted_cash_flow(
            replace(audit.model.inputs, terminal_growth=Decimal("0.01")),
            audit.tv_corrected.conventions)
        assert wide.spread_to_terminal_growth > WACC_GROWTH_SPREAD_FLOOR
        assert wacc_growth_spread_finding(wide) is None


class TestSensitivityIsReportedWithEveryDcf:
    def test_the_fifty_basis_point_band(self, audit):
        down, up = audit.sensitivity
        assert quantize_price(down.share_price) == Decimal("2076.86")
        assert quantize_price(up.share_price) == Decimal("2749.11")

    def test_it_appears_as_a_measurement_not_a_finding(self, audit):
        labels = [m.label for m in audit.rules.measurements]
        assert any("g -50bp" in label for label in labels)
        assert any("g +50bp" in label for label in labels)

    def test_the_band_is_computed_around_the_declared_growth_rate(self, audit):
        down, up = terminal_growth_sensitivity(
            audit.model.inputs, audit.tv_corrected.conventions)
        assert down.terminal_growth == Decimal("0.0395")
        assert up.terminal_growth == Decimal("0.0495")


class TestTheClassBoundaryUnderRealFindings:
    def test_seven_findings_five_class_a_two_class_b(self, audit):
        by_class = {}
        for finding in audit.rules.findings:
            by_class.setdefault(finding.rule.rule_class, []).append(finding.rule.id)
        assert len(by_class["correctness"]) == 5
        assert sorted(by_class["model_shape"]) == sorted([DEFECTS[2], DEFECTS[3]])

    def test_an_exception_moves_one_finding_and_leaves_the_rest(self, tsmc_workbook):
        excepted = audit_workbook(
            tsmc_workbook, published_price_cell="B27", externals={},
            exceptions=TV_SHARE_EXCEPTION, as_of=TODAY)
        assert [f.rule.id for f in excepted.rules.excepted] == [DEFECTS[2]]
        assert DEFECTS[3] in {f.rule.id for f in excepted.rules.blocking}
        assert excepted.passed is False           # five Class A remain

    def test_the_exception_is_published_with_the_output(self, tsmc_workbook):
        """6.5: relied upon means displayed, not merely consumed by the gate."""
        excepted = audit_workbook(
            tsmc_workbook, published_price_cell="B27", externals={},
            exceptions=TV_SHARE_EXCEPTION, as_of=TODAY)
        assert len(excepted.rules.disclosures) == 1
        disclosure = excepted.rules.disclosures[0]
        assert disclosure.startswith("Exception: `long_duration_asset` —")
        assert "86.75%" in disclosure and "75.00% threshold" in disclosure

    def test_an_expired_exception_stops_satisfying_it(self, tsmc_workbook):
        lapsed = audit_workbook(
            tsmc_workbook, published_price_cell="B27", externals={},
            exceptions=TV_SHARE_EXCEPTION, as_of=date(2027, 3, 1))
        assert lapsed.rules.excepted == []
        assert DEFECTS[2] in {f.rule.id for f in lapsed.rules.blocking}
