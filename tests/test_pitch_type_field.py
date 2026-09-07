"""P3.1 — framework 1.4h, the type field: dominant segment by revenue AND by profit.

The join key C1 hangs off. It decides which industry section 2 analyses and
which comp set section 4 uses, which is why 1.4h makes GICS the default and
profit-weighted reality the override.

Every expected value below is hand-computed from the filing's own segment
figures, and written before the module existed. The pure tests build a panel
from literals so they run without a database; the DB-backed one asserts the
live facts table produces those same literals.

The AVGO case is what shaped the design. Its FY2025 revenue-dominant and
profit-dominant segments AGREE -- and the agreement is worth 467m out of 42bn,
a 1.11pp profit split, against a 19-point segment margin gap. A binary argmax
type field would hand section 2 the semiconductor comp set while half the
profit is 77%-margin enterprise software. So a near-tie has to be a state of
its own, not a pass.
"""
from datetime import date
from decimal import Decimal

import pytest

from src.facts.api import Fact, PanelCell, SegmentPanel
from src.pitch.types import (
    AGREED,
    CONTEST_THRESHOLD,
    CONTESTED,
    DISAGREED,
    RECONCILING_ITEM,
    TypeField,
    TypeFieldError,
)

SEG_AXIS = "us-gaap:StatementBusinessSegmentsAxis"
AVGO, AMD = 1730168, 2488

Q = Decimal("0.0001")


def _fact(concept, value, member, period_end):
    qname = ("us-gaap:Revenues" if concept == "revenue"
             else "us-gaap:OperatingIncomeLoss")
    return Fact(concept=concept, value=Decimal(value), unit="USD", qname=qname,
                period_type="duration",
                period_start=date(period_end.year - 1, 11, 1),
                period_end=period_end, segments={SEG_AXIS: member},
                accession="0001730168-25-000121", filed_date=period_end,
                fy=period_end.year, source="instance")


def panel(period_end, rows, *, cik=AVGO):
    """rows: {member_qname: (revenue | None, operating_income | None)}"""
    cells = {}
    for member, (rev, oi) in rows.items():
        facts = {}
        if rev is not None:
            facts["revenue"] = _fact("revenue", rev, member, period_end)
        if oi is not None:
            facts["operating_income"] = _fact(
                "operating_income", oi, member, period_end)
        cells[(period_end, member)] = PanelCell(member=member, facts=facts)
    return SegmentPanel(cik=cik, axis=SEG_AXIS,
                        concepts=("revenue", "operating_income"),
                        periods=[(date(period_end.year - 1, 11, 1), period_end)],
                        cells=cells, consolidated={})


# Broadcom FY2025 (10-K 0001730168-25-000121, period ending 2025-11-02).
AVGO_2025 = date(2025, 11, 2)
AVGO_FY2025 = panel(AVGO_2025, {
    "avgo:SemiconductorSolutionsMember": ("36858000000", "21232000000"),
    "avgo:InfrastructureSoftwareMember": ("27029000000", "20765000000"),
})

# Broadcom FY2022 -- carries an unallocated-expenses reconciling item.
AVGO_2022 = date(2022, 10, 30)
AVGO_FY2022 = panel(AVGO_2022, {
    "avgo:SemiconductorSolutionsMember": ("25818000000", "15075000000"),
    "avgo:InfrastructureSoftwareMember": ("7385000000", "5219000000"),
    "avgo:UnallocatedExpensesMember": ("0", "-6069000000"),
})

# AMD FY2023: revenue-dominant Client And Gaming, profit-dominant Embedded.
AMD_2023 = date(2023, 12, 30)
AMD_FY2023 = panel(AMD_2023, {
    "amd:DatacenterMember": ("6496000000", "1267000000"),
    "amd:EmbeddedMember": ("5321000000", "2628000000"),
    "amd:ClientAndGamingMember": ("10863000000", "925000000"),
}, cik=AMD)

# AMD FY2025: one segment leads both, but by under 10pp of profit.
AMD_2025 = date(2025, 12, 27)
AMD_FY2025 = panel(AMD_2025, {
    "amd:DatacenterMember": ("16635000000", "3603000000"),
    "amd:EmbeddedMember": ("3454000000", "1243000000"),
    "amd:ClientAndGamingMember": ("14550000000", "2855000000"),
}, cik=AMD)


# ---------------------------------------------------------------------------
# The AVGO near-tie: the case the contested state exists for
# ---------------------------------------------------------------------------

class TestBroadcomFY2025:
    """36,858 / 27,029 revenue and 21,232 / 20,765 operating profit."""

    def setup_method(self):
        self.tf = TypeField.from_panel(AVGO_FY2025, AVGO_2025, gics="Semiconductors")

    def test_the_same_segment_leads_revenue_and_profit(self):
        assert self.tf.dominant_by_revenue == "Semiconductor Solutions"
        assert self.tf.dominant_by_profit == "Semiconductor Solutions"

    def test_the_revenue_split_matches_the_filing(self):
        """36,858 / 63,887 = 57.69%. The Bloomberg DES rounds it to 57.7."""
        assert self.tf.revenue_share.quantize(Q) == Decimal("0.5769")

    def test_the_profit_split_is_a_near_tie(self):
        """21,232 / 41,997 = 50.56%. 467m of 42bn separates the two."""
        assert self.tf.profit_share.quantize(Q) == Decimal("0.5056")
        assert self.tf.profit_gap.quantize(Q) == Decimal("0.0111")

    def test_a_gap_inside_the_threshold_is_contested_not_agreed(self):
        assert self.tf.profit_gap < CONTEST_THRESHOLD
        assert self.tf.verdict == CONTESTED

    def test_contested_forces_section_2_to_cover_both_types(self):
        """C1: the comp set cannot quietly inherit the single GICS type."""
        assert self.tf.requires_both_types is True

    def test_the_margin_gap_is_what_makes_the_tie_material(self):
        """57.60% against 76.82% -- these are not the same business."""
        by_label = {s.label: s for s in self.tf.shares}
        assert by_label["Semiconductor Solutions"].margin.quantize(Q) == Decimal("0.5760")
        assert by_label["Infrastructure Software"].margin.quantize(Q) == Decimal("0.7682")


# ---------------------------------------------------------------------------
# The other three states
# ---------------------------------------------------------------------------

def test_amd_fy2023_is_a_genuine_disagreement():
    """Client And Gaming sells the most; Embedded earns the most."""
    tf = TypeField.from_panel(AMD_FY2023, AMD_2023)
    assert tf.dominant_by_revenue == "Client And Gaming"
    assert tf.dominant_by_profit == "Embedded"
    assert tf.revenue_share.quantize(Q) == Decimal("0.4790")   # 10,863 / 22,680
    assert tf.profit_share.quantize(Q) == Decimal("0.5452")    # 2,628 / 4,820
    assert tf.verdict == DISAGREED
    assert tf.requires_both_types is True


def test_amd_fy2025_is_contested_although_one_segment_leads_both():
    """Datacenter leads both, on 46.79% of profit against 37.07%: 9.71pp."""
    tf = TypeField.from_panel(AMD_FY2025, AMD_2025)
    assert tf.dominant_by_revenue == tf.dominant_by_profit == "Datacenter"
    assert tf.profit_gap.quantize(Q) == Decimal("0.0971")
    assert tf.verdict == CONTESTED


def test_broadcom_fy2022_is_agreed():
    """15,075 against 5,219 ex-unallocated: 74.28% vs 25.72%, a 48.57pp gap."""
    tf = TypeField.from_panel(AVGO_FY2022, AVGO_2022)
    assert tf.dominant_by_revenue == tf.dominant_by_profit == "Semiconductor Solutions"
    assert tf.profit_share.quantize(Q) == Decimal("0.7428")
    assert tf.profit_gap.quantize(Q) == Decimal("0.4857")
    assert tf.verdict == AGREED
    assert tf.requires_both_types is False


def test_the_gap_is_measured_before_rounding_not_after():
    """AMD FY2023: 0.5452282 - 0.2628631 = 0.2823651, which rounds to 0.2824.

    Quantising the shares first and subtracting gives 0.2823. One ulp here and
    irrelevant, but at the threshold it decides the verdict, so the gap comes
    from the full-precision shares.
    """
    tf = TypeField.from_panel(AMD_FY2023, AMD_2023)
    assert tf.profit_gap.quantize(Q) == Decimal("0.2824")


# ---------------------------------------------------------------------------
# Reconciling items
# ---------------------------------------------------------------------------

class TestReconcilingItems:
    """1.3: a period's breakdown comes from one filing, and that filing tags
    things on the segment axis which are not segments. AVGO tags unallocated
    expenses there with zero revenue and -6,069m of profit. Counted as a
    segment it corrupts the profit denominator and the argmax both; dropped
    silently it is a figure that left the panel with nobody told."""

    def setup_method(self):
        self.tf = TypeField.from_panel(AVGO_FY2022, AVGO_2022)

    def test_a_zero_revenue_member_is_not_a_business_segment(self):
        assert [s.label for s in self.tf.shares] == [
            "Semiconductor Solutions", "Infrastructure Software"]

    def test_it_is_excluded_by_name_never_silently(self):
        assert [(e.label, e.reason) for e in self.tf.excluded] == [
            ("Unallocated Expenses", RECONCILING_ITEM)]

    def test_the_profit_denominator_excludes_it(self):
        """15,075 / (15,075 + 5,219), not 15,075 / 14,225."""
        assert self.tf.profit_share.quantize(Q) == Decimal("0.7428")

    def test_shares_sum_to_one_across_the_business_segments(self):
        assert sum(s.profit_share for s in self.tf.shares) == Decimal(1)
        assert sum(s.revenue_share for s in self.tf.shares) == Decimal(1)


# ---------------------------------------------------------------------------
# Refusals. A type field is derived; there is no path that asserts one.
# ---------------------------------------------------------------------------

class TestRefusals:
    def test_a_revenue_bearing_segment_without_profit_refuses(self):
        """1.3: segment operating profit is required, not optional."""
        p = panel(AVGO_2025, {
            "avgo:SemiconductorSolutionsMember": ("36858000000", "21232000000"),
            "avgo:InfrastructureSoftwareMember": ("27029000000", None),
        })
        with pytest.raises(TypeFieldError, match="Infrastructure Software"):
            TypeField.from_panel(p, AVGO_2025)

    def test_a_period_with_no_segments_refuses(self):
        with pytest.raises(TypeFieldError, match="no reportable segment"):
            TypeField.from_panel(panel(AVGO_2025, {}), AVGO_2025)

    def test_non_positive_aggregate_profit_refuses(self):
        """A profit-weighted classification of a loss-making panel is undefined."""
        p = panel(AVGO_2025, {
            "avgo:AMember": ("100", "-60"),
            "avgo:BMember": ("100", "-40"),
        })
        with pytest.raises(TypeFieldError, match="aggregate segment profit"):
            TypeField.from_panel(p, AVGO_2025)

    def test_a_single_segment_company_is_agreed_and_needs_one_type(self):
        p = panel(AVGO_2025, {"avgo:OnlyMember": ("100", "40")})
        tf = TypeField.from_panel(p, AVGO_2025)
        assert tf.verdict == AGREED and tf.requires_both_types is False
        assert tf.profit_gap == Decimal(1)


# ---------------------------------------------------------------------------
# DB-backed: the live facts table produces the literals above
# ---------------------------------------------------------------------------

def _loaded(cik) -> bool:
    try:
        from src.db import get_conn
        with get_conn() as conn:
            return conn.execute(
                "SELECT count(*) > 0 FROM facts WHERE cik = %s", (cik,)).fetchone()[0]
    except Exception:
        return False


@pytest.mark.skipif(not _loaded(AVGO), reason="AVGO facts not loaded")
def test_the_live_panel_reproduces_the_broadcom_type_field():
    from src.facts.api import get_segment_panel
    live = get_segment_panel(AVGO, years=5)
    tf = TypeField.from_panel(live, AVGO_2025, gics="Semiconductors")
    assert tf.dominant_by_revenue == "Semiconductor Solutions"
    assert tf.revenue_share.quantize(Q) == Decimal("0.5769")
    assert tf.profit_gap.quantize(Q) == Decimal("0.0111")
    assert tf.verdict == CONTESTED
