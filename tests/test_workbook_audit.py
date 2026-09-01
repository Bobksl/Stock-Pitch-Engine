"""P2.6 — auditing a foreign workbook: defects 1, 6 and 7.

The three convention defects, the ones that leave no trace in any value the
workbook displays. Each assertion below checks not just that the rule fired
but that the finding carries the evidence a modeller would need to act on it:
the offending formula, and the consequence in the model's own units.
"""
from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest

from src.qc.rules import CLASS_A, DEFECTS
from src.qc.valuation_rules import convention_findings
from src.valuation.excel.audit import audit_workbook
from src.valuation.inputs import Conventions
from src.valuation.money import as_percent, quantize_price

TODAY = date(2026, 9, 1)


@pytest.fixture(scope="module")
def audit(request):
    workbook = request.path.parent / "fixtures" / "tsmc_model.xlsx"
    return audit_workbook(workbook, published_price_cell="B27", as_of=TODAY)


class TestReproductionComesFirst:
    def test_the_published_target_is_reproduced_before_anything_is_criticised(
            self, audit):
        assert audit.reproduced is True
        assert quantize_price(audit.as_built.share_price) == Decimal("1732.66")

    def test_the_three_runs_are_distinct(self, audit):
        assert quantize_price(audit.tv_corrected.share_price) == Decimal("2359.34")
        assert quantize_price(audit.spec.share_price) == Decimal("2321.64")

    def test_correcting_everything_is_not_the_same_as_correcting_defect_one(
            self, audit):
        """The audit's 'corrected' row is defect 1 alone. Conflating the two
        loses the finding that the arithmetic error was masking TV dominance."""
        assert audit.tv_corrected.share_price != audit.spec.share_price


class TestTheThreeConventionDefects:
    def test_exactly_three_findings_and_all_are_class_a(self, audit):
        assert len(audit.rules.findings) == 3
        assert {f.rule.rule_class for f in audit.rules.findings} == {CLASS_A}

    def test_they_are_defects_one_six_and_seven(self, audit):
        found = {f.rule.id for f in audit.rules.findings}
        assert found == {DEFECTS[1], DEFECTS[6], DEFECTS[7]}

    def test_the_audit_blocks(self, audit):
        assert audit.passed is False
        assert len(audit.rules.blocking) == 3
        assert audit.rules.excepted == []

    def _detail(self, audit, defect: int) -> str:
        return next(f.detail for f in audit.rules.findings
                    if f.rule.id == DEFECTS[defect])

    def test_defect_one_quotes_the_formula_and_the_consequence(self, audit):
        detail = self._detail(audit, 1)
        assert "=N16*(1+B17)/(B13-B17)" in detail
        assert "N16" in detail and "not N14" in detail
        assert "TWD 1,732.66 to TWD 2,359.34" in detail

    def test_defect_six_quotes_the_formula_and_both_weightings(self, audit):
        detail = self._detail(audit, 6)
        assert "=36.31-B5" in detail
        assert "2.78%" in detail and "2.71%" in detail
        assert "7.5827%" in detail and "7.5858%" in detail

    def test_defect_seven_quotes_the_factor_and_the_undiscounted_row(self, audit):
        detail = self._detail(audit, 7)
        assert "=1/POWER(1+B13,1/6)" in detail
        assert "=I14*I15" in detail
        assert "16.67%" in detail


class TestMeasurementsOnEveryRun:
    def test_terminal_value_share_is_reported_pass_or_fail(self, audit):
        labels = {m.label: m for m in audit.rules.measurements}
        assert labels["Terminal value share (as built)"].value == Decimal("81.78")
        assert labels["Terminal value share (TV corrected)"].value == Decimal("86.75")

    def test_the_arithmetic_error_was_masking_terminal_value_dominance(self, audit):
        """Defects 1 and 2, the pair that justifies this layer.

        As built, terminal value looks like an unremarkable 81.8% of
        enterprise value. Repair the arithmetic and it is 86.8%, above the
        75% threshold. Two errors offsetting into a believable number.
        """
        as_built = as_percent(audit.as_built.terminal_value_share)
        corrected = as_percent(audit.tv_corrected.terminal_value_share)
        assert as_built < Decimal("85") < corrected

    def test_the_spread_is_reported_with_its_threshold(self, audit):
        spread = next(m for m in audit.rules.measurements
                      if m.label == "WACC less terminal growth")
        assert spread.value == Decimal("3.13")
        assert spread.threshold == Decimal("4.00")
        assert spread.unit == "pp"

    def test_measurements_do_not_block(self, audit):
        """They are not warnings. Removing the findings would let this pass."""
        from src.qc.findings import FindingSet
        assert FindingSet(measurements=audit.rules.measurements,
                          as_of=TODAY).passed is True


class TestACleanModelRaisesNothing:
    def test_spec_conventions_produce_no_convention_findings(self, audit):
        clean = replace(audit.model, conventions=Conventions.SPEC)
        assert convention_findings(clean, audit.spec, audit.spec) == []

    @pytest.mark.parametrize("field,defect", [
        ("terminal_value_base", 1),
        ("equity_weight_basis", 6),
        ("stub_policy", 7),
    ])
    def test_each_convention_fires_exactly_its_own_rule(self, audit, field, defect):
        """One defective convention at a time, against an otherwise clean model."""
        conventions = replace(
            Conventions.SPEC, **{field: getattr(audit.model.conventions, field)})
        model = replace(audit.model, conventions=conventions)
        findings = convention_findings(model, audit.as_built, audit.tv_corrected)
        assert [f.rule.id for f in findings] == [DEFECTS[defect]]


class TestClassAResistsAnExceptionStore:
    def test_a_class_b_exception_does_not_touch_the_class_a_findings(self, audit,
                                                                     tsmc_workbook):
        """A live exception for an unrelated Class B rule changes nothing."""
        store = """
        tv_share:
          condition: terminal_value_share
          reason: long_duration_asset
          detail: accepted
          author: Bob Liang
          date: 2026-08-31
          expiry: 2027-08-31
        """
        with_store = audit_workbook(tsmc_workbook, published_price_cell="B27",
                                    exceptions=store, as_of=TODAY)
        assert with_store.passed is False
        assert len(with_store.rules.blocking) == 3
