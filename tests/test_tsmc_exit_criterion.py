"""P2.9 — the Phase 2 exit criterion, asserted in one place.

    Reproduce the TSMC model's published target of TWD 1,732.66,
    then flag all eight findings in Audit section 2.

Both halves, and the second one asserted as EXACTLY eight rather than at
least eight. That direction matters as much as the other: a gate that fires
a ninth finding on a model whose defects are known is a gate that will fire
spurious findings on models whose defects are not, and a reviewer who learns
to skim the list has lost the thing the list was for.

This is the only place an exact total is asserted. Every other test scopes
itself to the rules it is about, so that adding a rule breaks this test --
deliberately, once, where the count is the subject -- rather than breaking a
dozen tests that never meant to count anything.
"""
from datetime import date
from decimal import Decimal

import pytest

from src.qc.rules import CLASS_A, CLASS_B, DEFECTS, rule
from src.valuation.excel.audit import audit_workbook
from src.valuation.money import as_percent, quantize_price

TODAY = date(2026, 9, 1)

#: The exit-criterion table: defect number -> class.
EXPECTED_CLASSES = {1: CLASS_A, 2: CLASS_B, 3: CLASS_B, 4: CLASS_A,
                    5: CLASS_A, 6: CLASS_A, 7: CLASS_A, 8: CLASS_B}


@pytest.fixture(scope="module")
def audit(request):
    workbook = request.path.parent / "fixtures" / "tsmc_model.xlsx"
    return audit_workbook(workbook, published_price_cell="B27", externals={},
                          as_of=TODAY)


class TestFirstHalfReproduce:
    def test_the_published_target_is_reproduced_to_the_cent(self, audit):
        assert quantize_price(audit.as_built.share_price) == Decimal("1732.66")
        assert audit.reproduced is True

    def test_against_the_workbooks_own_cached_value_not_a_transcription(self, audit):
        assert quantize_price(audit.model.published_price) == Decimal("1732.66")


class TestSecondHalfFlagAllEight:
    def test_exactly_eight_findings(self, audit):
        """Not seven, and not nine."""
        assert len(audit.rules.findings) == 8

    def test_every_defect_in_the_table_is_present_exactly_once(self, audit):
        found = [f.rule.id for f in audit.rules.findings]
        assert sorted(found) == sorted(DEFECTS[n] for n in range(1, 9))
        assert len(found) == len(set(found))

    @pytest.mark.parametrize("defect,expected", sorted(EXPECTED_CLASSES.items()))
    def test_each_defect_carries_the_class_the_table_specifies(
            self, audit, defect, expected):
        finding = next(f for f in audit.rules.findings
                       if f.rule.id == DEFECTS[defect])
        assert finding.rule.rule_class == expected

    def test_five_class_a_and_three_class_b(self, audit):
        classes = [f.rule.rule_class for f in audit.rules.findings]
        assert classes.count(CLASS_A) == 5
        assert classes.count(CLASS_B) == 3

    def test_every_finding_cites_a_spec_section_and_carries_evidence(self, audit):
        for finding in audit.rules.findings:
            assert finding.rule.spec_ref
            assert len(finding.detail) > 40, finding.rule.id

    def test_the_audit_blocks_publication(self, audit):
        assert audit.passed is False
        assert len(audit.rules.blocking) == 8


class TestTheMaterialNumbers:
    """The figures Audit section 2 publishes, reproduced independently."""

    def test_the_corrected_target(self, audit):
        assert quantize_price(audit.tv_corrected.share_price) == Decimal("2359.34")

    def test_the_enterprise_value_bridge_both_ways(self, audit):
        assert quantize_price(audit.as_built.enterprise_value) == Decimal("43307.82")
        assert quantize_price(audit.tv_corrected.enterprise_value) == Decimal(
            "59557.64")

    def test_terminal_value_share_and_spread(self, audit):
        assert as_percent(audit.tv_corrected.terminal_value_share) == Decimal("86.75")
        assert as_percent(audit.tv_corrected.spread_to_terminal_growth) == Decimal(
            "3.13")

    def test_the_fifty_basis_point_band(self, audit):
        down, up = audit.sensitivity
        assert quantize_price(down.share_price) == Decimal("2076.86")
        assert quantize_price(up.share_price) == Decimal("2749.11")


class TestNoClassAIsExceptionable:
    def test_the_three_class_b_defects_are_the_only_exceptionable_ones(self, audit):
        exceptionable = {f.rule.id for f in audit.rules.findings
                         if f.rule.exceptionable}
        assert exceptionable == {DEFECTS[2], DEFECTS[3], DEFECTS[8]}

    @pytest.mark.parametrize("defect", [1, 4, 5, 6, 7])
    def test_declaring_an_exception_for_a_class_a_defect_will_not_load(self, defect):
        from src.qc.exceptions import ExceptionError, load_exceptions
        store = (f"k:\n  condition: {DEFECTS[defect]}\n"
                 f"  reason: long_duration_asset\n  detail: d\n  author: a\n"
                 f"  date: 2026-01-01\n  expiry: 2027-01-01\n")
        with pytest.raises(ExceptionError, match="Class A"):
            load_exceptions(store)

    def test_excepting_all_three_class_b_defects_still_blocks(self, tsmc_workbook):
        """Five Class A findings remain, and no store contents clears them."""
        store = "\n".join(
            f"e{n}:\n  condition: {DEFECTS[n]}\n  reason: long_duration_asset\n"
            f"  detail: accepted for the demo\n  author: Bob Liang\n"
            f"  date: 2026-08-31\n  expiry: 2027-08-31\n"
            for n in (2, 3, 8))
        audit = audit_workbook(tsmc_workbook, published_price_cell="B27",
                               externals={}, exceptions=store, as_of=TODAY)
        assert len(audit.rules.excepted) == 3
        assert len(audit.rules.disclosures) == 3
        assert audit.passed is False
        assert {f.rule.rule_class for f in audit.rules.blocking} == {CLASS_A}


class TestTheReportIsLegible:
    def test_it_names_the_reproduction_before_the_criticism(self, audit):
        rendered = audit.render()
        assert rendered.index("reproduced") < rendered.index("BLOCKING")

    def test_measurements_are_printed_on_a_failing_run(self, audit):
        """4.6: the measured TV share is reported every run, pass or fail."""
        rendered = audit.render()
        assert "reported every run, pass or fail" in rendered
        assert "86.75%" in rendered and "81.78%" in rendered

    def test_the_verdict_is_unambiguous(self, audit):
        assert audit.render().rstrip().endswith("publication blocked")
