"""P3.7 — framework 2.3: the comp set, in two tiers, manually approved.

    "Direct competitors: same customer, same buying decision, comparable scale
     -- used by structural analysis (2.5).
     Valuation reference: similar economics, growth, margin profile -- used by
     section 4 comps.
     Overlapping but distinct. A 10x size gap with a different customer base
     means NOT a direct competitor. Auto-proposed from the type field and
     revenue-model tags; MANUALLY APPROVED, with written justification per
     member."

Two of 2.7's five conditions are gate rules and three are construction-time
invariants (spec v1.3). The invariants are tested here as REFUSALS: a member
without a tier or a justification does not exist, so it cannot reach the gate
and there is no rule for it. The one gate rule this module answers is
`comp_set_not_type_justified`, which is C1.
"""
from datetime import date
from decimal import Decimal

import pytest

from src.pitch.compset import (
    TIER_DIRECT,
    TIER_VALUATION,
    CompSet,
    CompSetError,
    CompSetMember,
    comp_set_type_finding,
)
from src.pitch.types import AGREED, CONTESTED

SEG_SEMI = "Semiconductor Solutions"
SEG_SOFT = "Infrastructure Software"

APPROVAL = {"approved_by": "Bob Liang", "approved_on": date(2026, 9, 8)}


def member(ticker, cik, *, tiers=(TIER_DIRECT,), covers=SEG_SEMI,
           justification="Custom silicon for the same hyperscaler buyers, "
                         "competing for the same sockets at comparable scale.",
           **kw):
    return CompSetMember(ticker=ticker, cik=cik, tiers=frozenset(tiers),
                         covers_type=covers, justification=justification,
                         **{**APPROVAL, **kw})


FIVE = (member("MRVL", 1835632), member("NVDA", 1045810),
        member("AMD", 2488), member("QCOM", 804328),
        member("IBM", 51143, covers=SEG_SOFT, tiers=(TIER_VALUATION,),
               justification="Mainframe and infrastructure software run on the "
                             "same acquire-and-harvest maintenance model."))


class _Type:
    """A stand-in for TypeField: only these two attributes are consulted."""

    def __init__(self, verdict, types):
        self.verdict = verdict
        self.requires_both_types = verdict != AGREED
        self._types = types

    @property
    def shares(self):
        return tuple(type("S", (), {"label": t})() for t in self._types)


CONTESTED_TYPE = _Type(CONTESTED, [SEG_SEMI, SEG_SOFT])
AGREED_TYPE = _Type(AGREED, [SEG_SEMI, SEG_SOFT])


# ---------------------------------------------------------------------------
# 2.7's three construction-time invariants: these defects cannot be built
# ---------------------------------------------------------------------------

class TestAMemberCannotExistWithoutItsJustification:
    def test_no_tier_refuses(self):
        with pytest.raises(CompSetError, match="tier"):
            member("MRVL", 1835632, tiers=())

    def test_an_unknown_tier_refuses(self):
        with pytest.raises(CompSetError, match="tier"):
            member("MRVL", 1835632, tiers=("sort_of_similar",))

    def test_an_empty_justification_refuses(self):
        with pytest.raises(CompSetError, match="justification"):
            member("MRVL", 1835632, justification="")

    def test_a_token_justification_refuses(self):
        """2.3 asks for a WRITTEN justification per member. 'competitor' is a
        label, not a reason, and a field that accepts it enforces nothing."""
        with pytest.raises(CompSetError, match="justification"):
            member("MRVL", 1835632, justification="competitor")

    def test_an_unapproved_member_refuses(self):
        """2.3: manually approved. An auto-proposed member is a proposal."""
        with pytest.raises(CompSetError, match="approved"):
            CompSetMember(ticker="MRVL", cik=1, tiers=frozenset({TIER_DIRECT}),
                          covers_type=SEG_SEMI, justification="a" * 40,
                          approved_by="", approved_on=date(2026, 9, 8))

    def test_a_well_formed_member_carries_both_tiers_if_it_earns_them(self):
        m = member("AMD", 2488, tiers=(TIER_DIRECT, TIER_VALUATION))
        assert m.is_direct and m.is_valuation_reference


class TestASectionCannotExistWithoutItsConclusions:
    def test_no_structural_conclusion_refuses(self):
        with pytest.raises(CompSetError, match="structural"):
            CompSet(members=FIVE, type_field=CONTESTED_TYPE,
                    structural_conclusion="",
                    profit_capture_conclusion="Profit sits with the design "
                                              "owners, not the foundries.")

    def test_no_profit_capture_conclusion_refuses(self):
        """2.7: 'no conclusion on profit capture'. 2.5d asks where in the value
        chain profit sits and whether it is moving."""
        with pytest.raises(CompSetError, match="profit capture"):
            CompSet(members=FIVE, type_field=CONTESTED_TYPE,
                    structural_conclusion="Rivalry is on design wins, not price.",
                    profit_capture_conclusion="")


def _built(members=FIVE, type_field=CONTESTED_TYPE):
    return CompSet(
        members=members, type_field=type_field,
        structural_conclusion="Rivalry runs on design wins and roadmap timing "
                              "rather than on price.",
        profit_capture_conclusion="Profit sits with the design owners; the "
                                  "foundries take capital risk for a fee.")


# ---------------------------------------------------------------------------
# C1 / comp_set_not_type_justified: the gate rule
# ---------------------------------------------------------------------------

class TestTypeCoverage:
    def test_a_contested_type_field_needs_both_types_covered(self):
        assert comp_set_type_finding(_built()) is None

    def test_covering_only_the_gics_type_fires_the_rule(self):
        """The exact failure 1.4h exists to prevent: half AVGO's profit is
        enterprise software and the comp set is all semiconductors."""
        semis_only = tuple(m for m in FIVE if m.covers_type == SEG_SEMI)
        finding = comp_set_type_finding(_built(members=semis_only))
        assert finding is not None
        assert finding.rule.id == "comp_set_not_type_justified"
        assert SEG_SOFT in finding.detail

    def test_the_finding_is_class_a(self):
        semis_only = tuple(m for m in FIVE if m.covers_type == SEG_SEMI)
        finding = comp_set_type_finding(_built(members=semis_only))
        assert finding.rule.rule_class == "correctness"
        assert not finding.rule.exceptionable

    def test_an_agreed_type_field_needs_only_the_dominant_type(self):
        """When one segment demonstrably carries the company, a single-type
        comp set is the right answer, not a lapse."""
        semis_only = tuple(m for m in FIVE if m.covers_type == SEG_SEMI)
        assert comp_set_type_finding(
            _built(members=semis_only, type_field=AGREED_TYPE)) is None


# ---------------------------------------------------------------------------
# Tiers are distinct, and the panel reads the direct tier
# ---------------------------------------------------------------------------

class TestTiers:
    def test_the_two_tiers_are_read_separately(self):
        cs = _built()
        assert {m.ticker for m in cs.direct} == {"MRVL", "NVDA", "AMD", "QCOM"}
        assert {m.ticker for m in cs.valuation_reference} == {"IBM"}

    def test_a_member_may_hold_both_tiers(self):
        both = member("AMD", 2488, tiers=(TIER_DIRECT, TIER_VALUATION))
        cs = _built(members=FIVE[:3] + (both,) + FIVE[4:])
        assert both in cs.direct and both in cs.valuation_reference

    def test_the_panel_membership_is_the_direct_tier(self):
        """2.3: direct competitors feed the structural analysis of 2.5, which
        is what the 2.4 industry panel serves."""
        assert set(_built().panel_members()) == {
            "MRVL": 1835632, "NVDA": 1045810, "AMD": 2488, "QCOM": 804328}.keys()

    def test_below_the_minimum_is_reported_not_raised(self):
        """4.8's minimum is Class B and exceptionable, so it is a finding the
        gate weighs, not a refusal to construct."""
        cs = _built(members=FIVE[:3])
        assert cs.below_minimum is True
