"""P0.6 — concept resolution and the typed fact API.

Pure tests run anywhere. The DB-backed tests carry hand-checked golden values
taken from MSFT's filings and skip when the facts table has not been loaded.
"""
from datetime import date
from decimal import Decimal

import pytest

from src.facts import api, concepts
from src.facts.api import Fact, PanelCell, pretty_member
from src.facts.concepts import ConceptError

MSFT = 789019
SEG_AXIS = "us-gaap:StatementBusinessSegmentsAxis"


def fact(concept="revenue", value="1", *, qname="us-gaap:Revenues", segments=None,
         start=date(2023, 7, 1), end=date(2024, 6, 30)):
    return Fact(concept=concept, value=Decimal(value), unit="USD", qname=qname,
                period_type="duration", period_start=start, period_end=end,
                segments=segments or {}, accession="0000950170-24-087843",
                filed_date=date(2024, 7, 30), fy=2024, source="instance")


# --------------------------------------------------------------------------
# concept map
# --------------------------------------------------------------------------

def test_concept_resolves_to_ordered_tags():
    c = concepts.concept("revenue")
    assert c.unit == "USD" and c.period_type == "duration"
    assert c.tags[0] == "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax", \
        "the ASC 606 tag must outrank the legacy ones"
    assert "us-gaap:Revenues" in c.tags


def test_segment_operating_profit_uses_the_same_tag_as_consolidated():
    """OperatingIncomeLoss carries the segment breakdown via its dimension."""
    assert concepts.concept("operating_income").tags == ("us-gaap:OperatingIncomeLoss",)


def test_instant_concepts_are_declared_as_instants():
    assert concepts.concept("cash_and_equivalents").period_type == "instant"


def test_unknown_concept_raises_and_names_the_alternatives():
    with pytest.raises(ConceptError, match="unknown concept"):
        concepts.concept("ebitda_adjusted_pro_forma")


def test_axis_lookup():
    assert concepts.axis("segment") == SEG_AXIS
    with pytest.raises(ConceptError, match="unknown axis"):
        concepts.axis("nonsense")


# --------------------------------------------------------------------------
# Fact: a number is never returned without its provenance
# --------------------------------------------------------------------------

def test_citation_names_accession_tag_and_period():
    c = fact().citation
    assert "0000950170-24-087843" in c
    assert "us-gaap:Revenues" in c
    assert "2023-07-01..2024-06-30" in c


def test_citation_of_a_dimensional_fact_names_the_member():
    f = fact(segments={SEG_AXIS: "msft:IntelligentCloudMember"})
    assert "msft:IntelligentCloudMember" in f.citation
    assert f.member == "msft:IntelligentCloudMember"


def test_consolidated_fact_has_no_member():
    assert fact().member is None


def test_instant_citation_shows_a_single_date():
    f = fact(concept="cash_and_equivalents", start=None)
    assert f.citation.endswith("2024-06-30")


def test_pretty_member_is_display_only():
    assert pretty_member("msft:IntelligentCloudMember") == "Intelligent Cloud"
    assert pretty_member(None) == "Consolidated"


# --------------------------------------------------------------------------
# margin is computed in code, from cited inputs
# --------------------------------------------------------------------------

def test_margin_is_computed_from_the_two_facts():
    cell = PanelCell(member="msft:IntelligentCloudMember", facts={
        "revenue": fact("revenue", "105362000000"),
        "operating_income": fact("operating_income", "49584000000"),
    })
    assert cell.margin == Decimal("0.4706")     # 49,584 / 105,362, hand-checked


def test_margin_is_none_when_an_input_is_missing():
    assert PanelCell("m", {"revenue": fact("revenue", "1")}).margin is None
    assert PanelCell("m", {}).margin is None


def test_margin_does_not_divide_by_zero():
    cell = PanelCell("m", {"revenue": fact("revenue", "0"),
                           "operating_income": fact("operating_income", "5")})
    assert cell.margin is None


# --------------------------------------------------------------------------
# segment filter SQL
# --------------------------------------------------------------------------

def test_segment_filter_none_matches_everything():
    assert api._segment_sql(None) == ("", {})


def test_segment_filter_empty_dict_means_consolidated_only():
    sql, _ = api._segment_sql({})
    assert "segments = '{}'::jsonb" in sql


def test_segment_filter_axis_name_matches_facts_carrying_that_axis():
    sql, params = api._segment_sql(SEG_AXIS)
    assert "segments ? %(axis)s" in sql
    assert params == {"axis": SEG_AXIS}


# --------------------------------------------------------------------------
# what counts as a reportable-segment row
# --------------------------------------------------------------------------

CONSOLIDATION = "srt:ConsolidationItemsAxis"
QUALIFIERS = {CONSOLIDATION: ["us-gaap:OperatingSegmentsMember"]}


def test_segment_axis_alone_is_a_segment_row():
    assert api.is_segment_row({SEG_AXIS: "msft:IntelligentCloudMember"}, SEG_AXIS, QUALIFIERS)


def test_operating_segments_qualifier_is_still_a_segment_row():
    """NVIDIA tags every segment figure with ConsolidationItemsAxis as well."""
    segs = {SEG_AXIS: "nvda:ComputeAndNetworkingSegmentMember",
            CONSOLIDATION: "us-gaap:OperatingSegmentsMember"}
    assert api.is_segment_row(segs, SEG_AXIS, QUALIFIERS)


def test_segment_crossed_with_geography_is_not_a_segment_row():
    """A finer slice, not a segment total — summing these would double-count."""
    segs = {SEG_AXIS: "msft:IntelligentCloudMember",
            "srt:StatementGeographicalAxis": "country:US"}
    assert not api.is_segment_row(segs, SEG_AXIS, QUALIFIERS)


def test_qualifier_axis_at_a_disallowed_member_is_not_a_segment_row():
    """Intersegment eliminations and corporate must not enter the panel."""
    segs = {SEG_AXIS: "nvda:GraphicsSegmentMember",
            CONSOLIDATION: "us-gaap:IntersegmentEliminationMember"}
    assert not api.is_segment_row(segs, SEG_AXIS, QUALIFIERS)


def test_consolidated_fact_is_not_a_segment_row():
    assert not api.is_segment_row({}, SEG_AXIS, QUALIFIERS)


# --------------------------------------------------------------------------
# DB-backed: hand-checked against MSFT's own filings
# --------------------------------------------------------------------------

def _facts_loaded() -> bool:
    try:
        from src.db import get_conn
        with get_conn() as conn:
            return conn.execute(
                "SELECT count(*) > 0 FROM facts WHERE cik = %s", (MSFT,)).fetchone()[0]
    except Exception:
        return False


loaded = pytest.mark.skipif(not _facts_loaded(), reason="MSFT facts not loaded")


@loaded
def test_revenue_series_matches_the_filings():
    series = {f.period_end: f.value for f in api.get_series(MSFT, "revenue", years=5)}
    assert series[date(2024, 6, 30)] == Decimal("245122000000")
    assert series[date(2023, 6, 30)] == Decimal("211915000000")
    assert all(f.citation for f in api.get_series(MSFT, "revenue", years=5))


@loaded
def test_get_fact_returns_one_cited_figure():
    f = api.get_fact(MSFT, "revenue", date(2024, 6, 30))
    assert f.value == Decimal("245122000000")
    assert f.qname == "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax"


@loaded
def test_get_fact_returns_none_for_a_period_never_reported():
    assert api.get_fact(MSFT, "revenue", date(1990, 6, 30)) is None


@loaded
def test_segment_panel_as_of_shows_the_originally_reported_segments():
    """MSFT restated its segments after FY2024; as_of must show the old basis."""
    panel = api.get_segment_panel(MSFT, years=1, as_of=date(2024, 12, 31))
    got = {pretty_member(m): panel.cells[(date(2024, 6, 30), m)].value("revenue")
           for (pe, m) in panel.cells if pe == date(2024, 6, 30)}
    assert got == {
        "Productivity And Business Processes": Decimal("77728000000"),
        "Intelligent Cloud": Decimal("105362000000"),
        "More Personal Computing": Decimal("62032000000"),
    }


@loaded
def test_segment_panel_current_view_shows_the_restated_segments():
    panel = api.get_segment_panel(MSFT, years=3)
    cloud = panel.cells[(date(2024, 6, 30), "msft:IntelligentCloudMember")]
    assert cloud.value("revenue") == Decimal("87464000000"), "restated basis"


@loaded
def test_segments_reconcile_to_the_consolidated_figure_on_both_bases():
    # years=5 on both bases so FY2024 is in range for the current view too,
    # whose newest period is the latest 10-K rather than FY2024.
    for as_of in (None, date(2024, 12, 31)):
        panel = api.get_segment_panel(MSFT, years=5, as_of=as_of)
        assert panel.segment_sum(date(2024, 6, 30), "revenue") == Decimal("245122000000")
        assert panel.reconciles(date(2024, 6, 30)) is True


@loaded
def test_panel_carries_segment_operating_profit():
    """The figure companyfacts cannot supply — framework 1.3."""
    panel = api.get_segment_panel(MSFT, years=1, as_of=date(2024, 12, 31))
    cell = panel.cells[(date(2024, 6, 30), "msft:IntelligentCloudMember")]
    assert cell.value("operating_income") == Decimal("49584000000")
    assert cell.margin == Decimal("0.4706")


NVDA = 1045810


def _nvda_loaded() -> bool:
    try:
        from src.db import get_conn
        with get_conn() as conn:
            return conn.execute(
                "SELECT count(*) > 0 FROM facts WHERE cik = %s", (NVDA,)).fetchone()[0]
    except Exception:
        return False


@pytest.mark.skipif(not _nvda_loaded(), reason="NVDA facts not loaded")
def test_panel_handles_a_filer_that_qualifies_every_segment_fact():
    """NVDA FY2025, hand-checked against the FY2025 10-K segment footnote."""
    panel = api.get_segment_panel(NVDA, years=5)
    fy25 = date(2025, 1, 26)
    got = {pretty_member(m): (c.value("revenue"), c.value("operating_income"))
           for (pe, m), c in panel.cells.items() if pe == fy25}
    assert got == {
        "Compute And Networking Segment": (Decimal("116193000000"), Decimal("82875000000")),
        "Graphics Segment": (Decimal("14304000000"), Decimal("5085000000")),
    }
    assert panel.reconciles(fy25) is True


@pytest.mark.skipif(not _nvda_loaded(), reason="NVDA facts not loaded")
def test_nvda_segment_revenue_resolves_via_the_legacy_tag():
    """NVDA tags segment revenue as us-gaap:Revenues; priority resolution finds it."""
    panel = api.get_segment_panel(NVDA, years=5)
    cell = panel.cells[(date(2025, 1, 26), "nvda:GraphicsSegmentMember")]
    assert cell.facts["revenue"].qname == "us-gaap:Revenues"


# --------------------------------------------------------------------------
# one period, one filing (member renaming)
# --------------------------------------------------------------------------

def _vintage(value, member, accession, filed):
    return Fact(concept="revenue", value=Decimal(value), unit="USD",
                qname="us-gaap:Revenues", period_type="duration",
                period_start=date(2023, 1, 30), period_end=date(2024, 1, 28),
                segments={SEG_AXIS: member}, accession=accession,
                filed_date=filed, fy=2024, source="instance")


def test_latest_vintage_drops_the_superseded_member_naming():
    """NVDA re-filed FY2024 segments under renamed members; both are current."""
    facts = [
        _vintage("47405000000", "nvda:ComputeAndNetworkingMember",
                 "0001045810-24-000029", date(2024, 2, 21)),
        _vintage("13517000000", "nvda:GraphicsMember",
                 "0001045810-24-000029", date(2024, 2, 21)),
        _vintage("47405000000", "nvda:ComputeAndNetworkingSegmentMember",
                 "0001045810-26-000021", date(2026, 2, 25)),
        _vintage("13517000000", "nvda:GraphicsSegmentMember",
                 "0001045810-26-000021", date(2026, 2, 25)),
    ]
    kept = api.latest_vintage(facts)
    assert len(kept) == 2, "merging two vintages would double every segment"
    assert {f.segments[SEG_AXIS] for f in kept} == {
        "nvda:ComputeAndNetworkingSegmentMember", "nvda:GraphicsSegmentMember"}
    assert sum(f.value for f in kept) == Decimal("60922000000")


def test_latest_vintage_keeps_every_period():
    older = _vintage("1", "nvda:GraphicsMember", "acc-1", date(2024, 2, 21))
    other_period = Fact(**{**older.__dict__, "period_end": date(2023, 1, 29),
                           "period_start": date(2022, 1, 31)})
    assert len(api.latest_vintage([older, other_period])) == 2


@pytest.mark.skipif(not _nvda_loaded(), reason="NVDA facts not loaded")
def test_every_filer_year_reconciles():
    """Segment revenue must add up to the consolidated total, all filers, all years."""
    from src.db import get_conn
    with get_conn() as conn:
        ciks = [r[0] for r in conn.execute(
            "SELECT cik FROM companies WHERE cik IS NOT NULL ORDER BY cik")]
    for cik in ciks:
        panel = api.get_segment_panel(cik, years=5)
        for _, period_end in panel.periods:
            assert panel.reconciles(period_end, "revenue") is True, \
                f"cik {cik} period {period_end} does not reconcile"
