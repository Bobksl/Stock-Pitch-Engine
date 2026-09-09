"""P3.3 — the framework 1.6 prose rules, and the drafts that trip them.

The phase-3 analogue of the phase-1 corruption test. Phase 1 proved the gate
catches a corrupted *figure*; these prove it catches a defective *claim*. Each
rule gets a degraded draft that trips it and nothing else, which is the
falsifiable half of the phase-3 exit criterion.

All three are Class A, by the test spec v1.3 states in 6.5: no reason in the
closed exception vocabulary could excuse a marketing adjective, an unsupported
pricing-power claim, or a segment mix shown revenue-only.
"""
from pathlib import Path

import pytest

from src.qc.claims import extract_claims
from src.qc.anchors import parse_index
from src.qc.prose_rules import (
    BANNED_PHRASES,
    banned_language_finding,
    prose_findings,
    segment_profit_finding,
    unsupported_claim_finding,
)

FIXTURES = Path(__file__).parent / "fixtures"
GOLDEN = (FIXTURES / "draft_msft_golden.md").read_text(encoding="utf-8")


def findings_on(md: str):
    return prose_findings(md, extract_claims(md), parse_index(md))


def rule_ids(md: str) -> set[str]:
    return {f.rule.id for f in findings_on(md)}


# ---------------------------------------------------------------------------
# The golden draft must stay clean. A new rule that reddens it is a bug in the
# rule until proven otherwise.
# ---------------------------------------------------------------------------

def test_the_phase_1_golden_draft_trips_none_of_them():
    assert rule_ids(GOLDEN) == set()


# ---------------------------------------------------------------------------
# 6.1 banned language
# ---------------------------------------------------------------------------

class TestBannedLanguage:
    def test_a_marketing_adjective_in_the_prose_is_caught(self):
        md = "Its best-in-class platform grew 12.0% [^F1].\n"
        finding = banned_language_finding(md)
        assert finding is not None
        assert finding.rule.id == "banned_language"
        assert "best-in-class" in finding.detail

    def test_the_finding_names_the_line_so_it_is_one_edit_to_fix(self):
        md = "Line one.\n\nA world-class franchise.\n"
        assert "line 3" in banned_language_finding(md).detail

    def test_every_phrase_in_the_6_1_list_is_caught(self):
        for phrase in BANNED_PHRASES:
            md = f"The company has a {phrase} position.\n"
            assert banned_language_finding(md) is not None, phrase

    def test_it_is_case_insensitive_and_hyphen_tolerant(self):
        assert banned_language_finding("A World Class result.\n") is not None
        assert banned_language_finding("An AI powered product.\n") is not None

    def test_a_banned_word_inside_a_longer_word_is_not_a_match(self):
        """'leading' is banned; 'misleading' and 'bleeding' are not."""
        assert banned_language_finding("A misleading chart.\n") is None

    def test_declarations_are_not_prose(self):
        """A member qname or a cell name is not marketing copy."""
        md = ("Revenue rose.\n\n## Citation index\n\n```yaml\n"
              "F1: {kind: fact, cik: 1, concept: revenue, "
              "period_end: 2025-01-01, segments: {a: x:BestInClassMember}}\n```\n")
        assert banned_language_finding(md) is None

    def test_a_code_span_is_not_prose(self):
        assert banned_language_finding("The `world-class` flag is set.\n") is None


# ---------------------------------------------------------------------------
# 1.4f / 1.6 — no number, no claim
# ---------------------------------------------------------------------------

class TestUnsupportedClaims:
    def _finding(self, md):
        return unsupported_claim_finding(md, extract_claims(md))

    def test_a_pricing_power_claim_with_no_number_is_caught(self):
        md = "The company has demonstrated pricing power with its customers.\n"
        finding = self._finding(md)
        assert finding is not None
        assert finding.rule.id == "unsupported_qualitative_claim"
        assert "pricing power" in finding.detail

    def test_the_same_claim_carrying_a_number_passes(self):
        md = ("Pricing power is visible: realised prices rose 4.2% [^M1] while "
              "input costs rose 9.1% [^M2].\n")
        assert self._finding(md) is None

    def test_an_operating_leverage_claim_with_no_number_is_caught(self):
        md = "Operating leverage should improve from here.\n"
        assert self._finding(md).rule.id == "unsupported_qualitative_claim"

    def test_the_supporting_number_must_be_in_the_same_sentence(self):
        """A number two sentences away is not support; it is proximity."""
        md = ("Revenue was $12.0 billion [^F1]. The business has real pricing "
              "power. Costs fell.\n")
        assert self._finding(md) is not None

    def test_a_year_is_not_a_supporting_number(self):
        """claims.py already refuses to treat a bare 2026 as a figure."""
        md = "Pricing power improved through 2026 and beyond.\n"
        assert self._finding(md) is not None

    def test_the_finding_quotes_the_offending_sentence(self):
        md = "The franchise enjoys durable pricing power everywhere.\n"
        assert "durable pricing power" in self._finding(md).detail

    def test_every_offending_sentence_is_reported_not_just_the_first(self):
        md = ("It has pricing power.\n\nIt also enjoys operating leverage.\n")
        detail = self._finding(md).detail
        assert "pricing power" in detail and "operating leverage" in detail


# ---------------------------------------------------------------------------
# 1.3 / 1.6 — segment revenue shown without segment profit
# ---------------------------------------------------------------------------

SEG = "us-gaap:StatementBusinessSegmentsAxis"


def _index_md(entries: str) -> str:
    return f"Body text.\n\n## Citation index\n\n```yaml\n{entries}\n```\n"


class TestSegmentProfit:
    """Checked against the citation index, not by parsing the rendered table.

    Anchor-based, like every other resolution in this codebase: the draft says
    which fact it stands on and the gate reads that, rather than inferring
    intent from Markdown column headers.
    """

    def test_a_segment_revenue_anchor_without_its_profit_is_caught(self):
        md = _index_md(
            "F1: {kind: fact, cik: 1, concept: revenue, period_end: 2025-11-02,\n"
            f"     segments: {{{SEG}: x:SemisMember}}}}")
        finding = segment_profit_finding(parse_index(md))
        assert finding is not None
        assert finding.rule.id == "segment_profit_missing"
        assert "Semis" in finding.detail

    def test_the_pair_passes(self):
        md = _index_md(
            "F1: {kind: fact, cik: 1, concept: revenue, period_end: 2025-11-02,\n"
            f"     segments: {{{SEG}: x:SemisMember}}}}\n"
            "F2: {kind: fact, cik: 1, concept: operating_income, "
            "period_end: 2025-11-02,\n"
            f"     segments: {{{SEG}: x:SemisMember}}}}")
        assert segment_profit_finding(parse_index(md)) is None

    def test_one_paired_member_does_not_excuse_an_unpaired_one(self):
        md = _index_md(
            "F1: {kind: fact, cik: 1, concept: revenue, period_end: 2025-11-02,\n"
            f"     segments: {{{SEG}: x:SemisMember}}}}\n"
            "F2: {kind: fact, cik: 1, concept: operating_income, "
            "period_end: 2025-11-02,\n"
            f"     segments: {{{SEG}: x:SemisMember}}}}\n"
            "F3: {kind: fact, cik: 1, concept: revenue, period_end: 2025-11-02,\n"
            f"     segments: {{{SEG}: x:SoftwareMember}}}}")
        assert "Software" in segment_profit_finding(parse_index(md)).detail

    def test_a_prior_period_comparative_is_the_recency_rule_s_business(self):
        """1.5's exhibit is struck at the latest cited period, and that is what
        this rule protects: showing the current mix revenue-only is what hides
        a small profitable segment. A prior-year segment revenue quoted for a
        comparison is governed by 6.3, which already requires its current-year
        comparative -- and the phase-1 golden draft does exactly that."""
        md = _index_md(
            "F1: {kind: fact, cik: 1, concept: revenue, period_end: 2025-11-02,\n"
            f"     segments: {{{SEG}: x:SemisMember}}}}\n"
            "F2: {kind: fact, cik: 1, concept: operating_income, "
            "period_end: 2025-11-02,\n"
            f"     segments: {{{SEG}: x:SemisMember}}}}\n"
            "F3: {kind: fact, cik: 1, concept: revenue, period_end: 2024-11-03,\n"
            f"     segments: {{{SEG}: x:SemisMember}}}}")
        assert segment_profit_finding(parse_index(md)) is None

    def test_a_consolidated_figure_is_not_a_segment(self):
        md = _index_md(
            "F1: {kind: fact, cik: 1, concept: revenue, period_end: 2025-11-02}")
        assert segment_profit_finding(parse_index(md)) is None

    def test_a_draft_with_no_index_has_no_segment_finding(self):
        """The unresolved-figure rule owns that failure, not this one."""
        assert segment_profit_finding({}) is None


# ---------------------------------------------------------------------------
# The degraded drafts: one rule each, and nothing else
# ---------------------------------------------------------------------------

DEGRADED = {
    "banned_language": "draft_avgo_banned_language.md",
    "unsupported_qualitative_claim": "draft_avgo_unsupported_claim.md",
    "segment_profit_missing": "draft_avgo_segment_profit_missing.md",
}


@pytest.mark.parametrize("rule_id,filename", sorted(DEGRADED.items()))
def test_each_degraded_draft_trips_exactly_its_own_rule(rule_id, filename):
    md = (FIXTURES / filename).read_text(encoding="utf-8")
    assert rule_ids(md) == {rule_id}


def test_the_clean_draft_the_degraded_ones_derive_from_passes():
    md = (FIXTURES / "draft_avgo_section1.md").read_text(encoding="utf-8")
    assert rule_ids(md) == set()
