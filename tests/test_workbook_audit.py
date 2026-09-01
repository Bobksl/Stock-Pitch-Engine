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

from src.qc.rules import CLASS_A, CLASS_B, DEFECTS
from src.qc.valuation_rules import convention_findings
from src.valuation.excel.audit import audit_workbook
from src.valuation.inputs import Conventions
from src.valuation.money import as_percent, quantize_price

TODAY = date(2026, 9, 1)


@pytest.fixture(scope="module")
def audit(request):
    workbook = request.path.parent / "fixtures" / "tsmc_model.xlsx"
    return audit_workbook(workbook, published_price_cell="B27", externals={},
                          as_of=TODAY)


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
    """Scoped to the convention rules on purpose.

    The audit's *total* finding count grows with every later step, so asserting
    an exact total here would make these tests churn for reasons unrelated to
    what they check. Exactly-eight belongs in the acceptance test, once.
    """

    def test_the_three_convention_findings_are_class_a(self, audit):
        findings = convention_findings(audit.model, audit.as_built,
                                       audit.tv_corrected)
        assert len(findings) == 3
        assert {f.rule.rule_class for f in findings} == {CLASS_A}

    def test_they_are_defects_one_six_and_seven(self, audit):
        findings = convention_findings(audit.model, audit.as_built,
                                       audit.tv_corrected)
        assert {f.rule.id for f in findings} == {DEFECTS[1], DEFECTS[6], DEFECTS[7]}

    def test_the_audit_blocks(self, audit):
        assert audit.passed is False
        blocking = {f.rule.id for f in audit.rules.blocking}
        assert {DEFECTS[1], DEFECTS[6], DEFECTS[7]} <= blocking
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

    def test_the_arithmetic_error_understated_terminal_value_dominance(self, audit):
        """Defects 1 and 2, the pair that justifies this layer.

        Precisely: as built, terminal value is 81.78% of enterprise value --
        ALREADY above the 75% threshold, so the Class B rule fires on the
        published model too. The error did not conceal the breach, it
        understated it, and what it really masked was the target price:
        TWD 1,732.66 against a true TWD 2,359.34.
        """
        as_built = as_percent(audit.as_built.terminal_value_share)
        corrected = as_percent(audit.tv_corrected.terminal_value_share)
        assert Decimal("75") < as_built < corrected
        assert as_built == Decimal("81.78") and corrected == Decimal("86.75")

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
    def test_a_class_b_exception_leaves_every_class_a_finding_blocking(
            self, tsmc_workbook):
        """A live Class B exception satisfies its own rule and nothing else.

        The five Class A findings are untouched by it, which is the property
        that makes Class A meaningful: there is no store contents that could
        clear them.
        """
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
                                    exceptions=store, externals={}, as_of=TODAY)
        blocking = {f.rule.id for f in with_store.rules.blocking}
        assert {DEFECTS[n] for n in (1, 4, 5, 6, 7)} <= blocking
        # Nothing Class A can ever reach the excepted list.
        assert {f.rule.rule_class for f in with_store.rules.excepted} == {CLASS_B}
        assert with_store.passed is False
