"""P2.7 — defects 4 and 5: the figures whose problem is what was never declared.

Neither defect is visible in any arithmetic. 0.0445 is an ordinary number to
multiply by and 1.22 is an ordinary beta; every computation involving them is
correct. What is missing is a declaration, so both route through the framework
6.4 provenance machinery Phase 1 built rather than through anything new.

The distinction the beta tests exist to pin down: `external.py` legitimately
permits a `beta_input` record -- regression inputs and peer betas SHOULD be
declared that way. The violation is using one *directly as the beta*.
"""
from dataclasses import replace
from decimal import Decimal

import pytest

from src.qc.external import load_records
from src.qc.rules import CLASS_A, DEFECTS
from src.qc.valuation_rules import (
    NOMINAL_RATE_UNITS,
    REAL_RATE_UNITS,
    beta_provenance_finding,
    provenance_findings,
    terminal_growth_provenance_finding,
)

REAL_GDP = """
tw_real_gdp:
  kind: macro_series
  value: 0.0445
  unit: real_gdp_growth
  source: Taiwan DGBAS real GDP growth
  as_of: 2026-08-01
"""

NOMINAL_GDP = REAL_GDP.replace("real_gdp_growth", "nominal_gdp_growth").replace(
    "tw_real_gdp", "tw_nominal_gdp").replace("real GDP", "nominal GDP")

BLOOMBERG_BETA = """
tsmc_beta:
  kind: beta_input
  value: 1.22
  unit: pure
  source: Bloomberg BETA screen
  as_of: 2026-08-01
"""


@pytest.fixture
def inputs(tsmc_model):
    return tsmc_model.inputs


class TestDefectFourTerminalGrowth:
    def test_an_undeclared_growth_rate_cannot_be_shown_to_be_nominal(self, inputs):
        finding = terminal_growth_provenance_finding(inputs)
        assert finding is not None
        assert finding.rule.id == DEFECTS[4]
        assert finding.rule.rule_class == CLASS_A
        assert "4.45%" in finding.detail
        assert "no declared provenance" in finding.detail

    def test_a_real_rate_declared_as_such_is_caught(self, inputs):
        declared = replace(inputs, provenance={"terminal_growth": "ext:tw_real_gdp"})
        finding = terminal_growth_provenance_finding(declared, load_records(REAL_GDP))
        assert finding is not None
        assert "real_gdp_growth" in finding.detail
        assert "Taiwan DGBAS" in finding.detail

    def test_a_nominal_rate_declared_as_such_passes(self, inputs):
        declared = replace(inputs,
                           provenance={"terminal_growth": "ext:tw_nominal_gdp"})
        assert terminal_growth_provenance_finding(
            declared, load_records(NOMINAL_GDP)) is None

    def test_an_unrecognised_unit_fails_rather_than_passing_by_default(self, inputs):
        """6.4: unit and scale are read, never inferred."""
        odd = load_records(REAL_GDP.replace("real_gdp_growth", "percent"))
        declared = replace(inputs, provenance={"terminal_growth": "ext:tw_real_gdp"})
        finding = terminal_growth_provenance_finding(declared, odd)
        assert finding is not None
        assert "neither nominal nor real" in finding.detail

    def test_citing_a_record_that_is_not_in_the_store_fails(self, inputs):
        declared = replace(inputs, provenance={"terminal_growth": "ext:missing"})
        finding = terminal_growth_provenance_finding(declared, {})
        assert finding is not None
        assert "not in the store" in finding.detail

    def test_the_two_unit_vocabularies_do_not_overlap(self):
        assert not set(NOMINAL_RATE_UNITS) & set(REAL_RATE_UNITS)


class TestDefectFiveBeta:
    def test_an_undeclared_beta_is_not_derived(self, inputs):
        finding = beta_provenance_finding(inputs)
        assert finding is not None
        assert finding.rule.id == DEFECTS[5]
        assert finding.rule.rule_class == CLASS_A
        assert finding.measured == Decimal("1.22")
        assert "peer-median unlevered relevered" in finding.detail

    def test_a_terminal_beta_used_directly_as_the_beta_is_caught(self, inputs):
        declared = replace(inputs, provenance={"beta": "ext:tsmc_beta"})
        finding = beta_provenance_finding(declared, load_records(BLOOMBERG_BETA))
        assert finding is not None
        assert "Bloomberg BETA screen" in finding.detail
        assert "INPUT to a beta computation, not the beta" in finding.detail

    def test_a_beta_derived_in_a_model_cell_passes(self, inputs):
        """4.4 is satisfied by computation, not by sourcing."""
        declared = replace(inputs, provenance={"beta": "model:beta_peer_relevered"})
        assert beta_provenance_finding(declared, {}) is None

    def test_declaring_beta_inputs_as_external_remains_legal(self):
        """The record itself is fine -- peer betas are exactly what external
        provenance exists for. Only using one AS the beta is the violation."""
        records = load_records(BLOOMBERG_BETA)
        assert records["tsmc_beta"].kind == "beta_input"


class TestBothTogether:
    def test_the_fixture_raises_exactly_defects_four_and_five(self, inputs):
        findings = provenance_findings(inputs)
        assert [f.rule.id for f in findings] == [DEFECTS[4], DEFECTS[5]]

    def test_a_fully_declared_model_raises_neither(self, inputs):
        declared = replace(inputs, provenance={
            "terminal_growth": "ext:tw_nominal_gdp",
            "beta": "model:beta_peer_relevered"})
        assert provenance_findings(declared, load_records(NOMINAL_GDP)) == []


class TestInTheAudit:
    def test_the_audit_carries_all_five_class_a_defects(self, tsmc_workbook):
        """Scoped to the Class A set, not to a total.

        The audit's total grows with each remaining step; exactly-eight is
        asserted once, in the acceptance test.
        """
        from src.valuation.excel.audit import audit_workbook
        audit = audit_workbook(tsmc_workbook, published_price_cell="B27",
                               externals={})
        class_a = {f.rule.id for f in audit.rules.findings
                   if f.rule.rule_class == CLASS_A}
        assert class_a == {DEFECTS[n] for n in (1, 4, 5, 6, 7)}
