"""Phase 3 acceptance — the exit criterion, asserted in one place.

    python scripts/draft_pitch.py AVGO --sections 1,2 --qc     # exit 0

Phases 0, 1 and 2 each had one falsifiable exit criterion and reported against
it rather than against a sense of doneness. Phase 3's is the first with no
published answer to reproduce: phase 0 pulled a segment panel, phase 1 caught a
deliberately corrupted figure, phase 2 reproduced TWD 1,732.66. A narrative
section has no equivalent, so this criterion tests two different things.

VERIFIABILITY -- every figure in the emitted draft resolves (C10), is from the
latest filed period (C12), and the five exhibits 1.5 and 2.6 require are all
present. The exhibit clause is what stops the criterion being satisfied
vacuously: a draft carrying no figures resolves all of them.

DETECTION -- each new 1.6 / 2.7 rule has a degraded draft that trips exactly it
and nothing else. This is the phase-3 analogue of phase 1's corruption test,
and it is the falsifiable half.

Only this test asserts the whole thing. Every other test in the suite scopes to
the rules it is about, or it churns whenever a rule is added.
"""
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"
AVGO = 1730168
FY2025, FY2024 = date(2025, 11, 2), date(2024, 11, 3)
COMP_SET = Path("config/comp_sets/avgo.yaml")


def _ready() -> bool:
    try:
        from src.facts.api import get_fact
        from src.ingest.prices import get_closes
        return (get_fact(AVGO, "revenue", FY2025) is not None
                and bool(get_closes("SPY", date(2022, 1, 1), date(2022, 3, 1))))
    except Exception:
        return False


live = pytest.mark.skipif(
    not _ready(), reason="AVGO facts and SPY prices must both be loaded")


@pytest.fixture(scope="module")
def drafted():
    from scripts.draft_pitch import build
    return build("AVGO", COMP_SET, period_end=FY2025, prior_period_end=FY2024,
                 calendar_year=2025, kpi_group="semiconductors",
                 gics="Semiconductors", benchmark="SPY")


@live
class TestClauseOneEveryFigureResolves:
    """C10 and C12, plus the non-vacuity floor."""

    def test_the_gate_passes(self, drafted):
        from src.qc.report import verify_draft
        report = verify_draft(drafted[2].markdown())
        assert report.failures == [], report.render()
        assert report.stale == [], report.render()
        assert report.passed, report.render()

    def test_the_draft_is_not_vacuously_clean(self, drafted):
        """Everything resolving is trivial for a draft with no figures."""
        from src.qc.claims import extract_claims
        assert len(extract_claims(drafted[2].markdown())) >= 60

    def test_all_five_required_exhibits_are_present(self, drafted):
        """1.5: revenue AND profit mix by segment, margin history, KPI
        snapshot. 2.6: industry panel, relative growth, peer drawdown."""
        md = drafted[2].markdown()
        for heading in ("Segment mix", "Margin history", "KPI snapshot",
                        "Industry panel", "Relative growth", "Peer drawdown"):
            assert heading in md, heading

    def test_the_segment_exhibit_shows_profit_beside_revenue(self, drafted):
        """1.3: segment profit is required, not optional."""
        md = drafted[2].markdown()
        assert "Operating profit ($m)" in md and "Revenue ($m)" in md

    def test_no_prose_rule_fires(self, drafted):
        from src.qc.anchors import parse_index
        from src.qc.claims import extract_claims
        from src.qc.prose_rules import prose_findings
        md = drafted[2].markdown()
        assert prose_findings(md, extract_claims(md), parse_index(md)) == []

    def test_the_comp_set_covers_the_contested_type_field(self, drafted):
        """C1. The set is approved in config/comp_sets/avgo.yaml, and a
        semiconductor-only set would fire here."""
        from src.pitch.compset import comp_set_type_finding
        assert comp_set_type_finding(drafted[1].comp_set) is None


@live
class TestClauseTwoTheTypeFieldIsDerived:
    """1.4h, hand-checked against Broadcom's FY2025 segment footnote."""

    def test_both_dominances_are_named_separately(self, drafted):
        tf = drafted[0].type_field
        assert tf.dominant_by_revenue == "Semiconductor Solutions"
        assert tf.dominant_by_profit == "Semiconductor Solutions"

    def test_the_splits_match_the_filing(self, drafted):
        """36,858 / 63,887 = 57.69% of revenue; 21,232 / 41,997 = 50.56% of
        segment profit. Hand-computed from the 10-K, not from the code."""
        tf = drafted[0].type_field
        q = Decimal("0.0001")
        assert tf.revenue_share.quantize(q) == Decimal("0.5769")
        assert tf.profit_share.quantize(q) == Decimal("0.5056")

    def test_the_near_tie_is_flagged_rather_than_passed(self, drafted):
        """467m of 42bn separates the two, on segment margins of 57.60% and
        76.82%. A binary argmax test calls this agreement."""
        tf = drafted[0].type_field
        assert tf.verdict == "contested"
        assert tf.requires_both_types is True

    def test_it_overrides_the_gics_label(self, drafted):
        assert drafted[0].type_field.overrides_gics is True


@live
class TestClauseThreeThePanelIsCalendarAligned:
    def test_at_least_five_members_share_one_calendar_column(self, drafted):
        panel = drafted[1].panel
        assert len(panel.members) >= 5
        assert panel.calendar_year == 2025

    def test_at_least_one_off_cycle_peer_is_excluded(self, drafted):
        """The path 2.4 cares about has to actually execute. Broadcom's peers
        close in September, December, January, May and June, so it does."""
        assert len(drafted[1].panel.excluded) >= 1

    def test_every_exclusion_is_named_in_the_draft(self, drafted):
        """Exclusion is 2.4's default and mis-assignment is never acceptable,
        so an excluded peer appears in the exhibit rather than vanishing."""
        md = drafted[2].markdown()
        for label in drafted[1].panel.excluded:
            assert label in md, label
            assert "EXCLUDED" in md

    def test_the_partition_is_exact(self, drafted):
        """A member in neither list would be a silent drop."""
        panel = drafted[1].panel
        considered = set(panel.considered) | set(panel.excluded)
        assert set(panel.members) | set(panel.excluded) == considered

    def test_nothing_was_assigned_to_the_nearest_year(self, drafted):
        """Every aligned member overlaps CY2025 by at least the declared floor;
        no peer was rounded into the column."""
        from src.pitch.panel import DEFAULT_MIN_OVERLAP_DAYS
        for label, aligned in drafted[1].panel.aligned.items():
            assert aligned.overlap_days >= DEFAULT_MIN_OVERLAP_DAYS, label


class TestClauseFourEachRuleHasADegradedDraft:
    """The falsifiable half, and the phase-3 analogue of phase 1's corruption
    test. Runs without a database: these are fixtures and pure rules."""

    DEGRADED = {
        "banned_language": "draft_avgo_banned_language.md",
        "unsupported_qualitative_claim": "draft_avgo_unsupported_claim.md",
        "segment_profit_missing": "draft_avgo_segment_profit_missing.md",
    }

    def _rules(self, md):
        from src.qc.anchors import parse_index
        from src.qc.claims import extract_claims
        from src.qc.prose_rules import prose_findings
        return {f.rule.id for f in prose_findings(md, extract_claims(md),
                                                  parse_index(md))}

    @pytest.mark.parametrize("rule_id,filename", sorted(DEGRADED.items()))
    def test_each_degraded_draft_trips_exactly_its_rule(self, rule_id, filename):
        md = (FIXTURES / filename).read_text(encoding="utf-8")
        assert self._rules(md) == {rule_id}

    def test_the_clean_draft_they_derive_from_trips_none(self):
        md = (FIXTURES / "draft_avgo_section1.md").read_text(encoding="utf-8")
        assert self._rules(md) == set()

    def test_every_prose_rule_in_the_registry_has_a_degraded_draft(self):
        """A rule with no draft that trips it is a rule nobody has shown to
        work. `comp_set_not_type_justified` is covered by its own unit test
        against the live type field, and `sizing_without_derivation` has no
        checker yet and is recorded as such."""
        covered = set(self.DEGRADED) | {"comp_set_not_type_justified"}
        pending = {"sizing_without_derivation"}
        from src.qc.rules import RULES
        phase3 = {r.id for r in RULES.values()
                  if r.spec_ref in ("1.6", "2.7", "6.1", "1.3")}
        assert phase3 - covered == pending
