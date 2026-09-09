"""P3.3 — rendering: the LLM writes prose with slots, Python supplies figures.

The structural half of P1. The gate already catches a hallucinated figure after
the fact; these prove the boundary holds before the fact, by refusing a
template that carries a numeral at all.

The end-to-end test is the one that matters: build the evidence from AVGO's
filings, render a section 1 template through it, and put the result through the
same numeric gate a hand-written draft goes through. If that passes, the
generator produces drafts the QC layer accepts.
"""
from datetime import date
from decimal import Decimal

import pytest

from src.pitch.draft import Draft, Figure, TemplateError, bare_numeral_finding, render
from src.qc.anchors import KIND_FACT, KIND_MODEL

AVGO = 1730168
FY2025, FY2024 = date(2025, 11, 2), date(2024, 11, 3)


def fig(name="revenue", *, kind=KIND_FACT, text="$63,887 million", body=None,
        cell=None, value=Decimal("63887000000")):
    return Figure(name=name, text=text, kind=kind,
                  body=body or {"cik": AVGO, "concept": "revenue",
                                "period_end": FY2025},
                  cell=cell, value=value)


# ---------------------------------------------------------------------------
# Markers are content-addressed (6.4)
# ---------------------------------------------------------------------------

class TestMarkers:
    def test_the_same_provenance_always_gets_the_same_marker(self):
        assert fig().marker == fig(name="something_else").marker

    def test_different_provenance_gets_a_different_marker(self):
        other = fig(body={"cik": AVGO, "concept": "revenue",
                          "period_end": FY2024})
        assert fig().marker != other.marker

    def test_the_marker_says_which_kind_it_is(self):
        assert fig().marker.startswith("F")
        assert fig(kind=KIND_MODEL, body={"cell": "gross_margin"}).marker \
            .startswith("M")

    def test_editing_prose_around_a_figure_does_not_renumber_it(self):
        """6.4: markers are content-addressed precisely so this holds."""
        figures = {"a": fig("a"), "b": fig("b", body={"cik": AVGO,
                                                     "concept": "capex",
                                                     "period_end": FY2025})}
        first = render("X {a} then {b}.\n", figures)
        second = render("Y {b} first, then {a}.\n", figures)
        assert first.figures["a"].marker == second.figures["a"].marker

    def test_two_slots_citing_one_fact_share_a_marker(self):
        figures = {"a": fig("a"), "b": fig("b")}
        drafted = render("{a} and again {b}.\n", figures)
        assert len(drafted.markers) == 1


# ---------------------------------------------------------------------------
# P1: a numeral in the template is the LLM computing
# ---------------------------------------------------------------------------

class TestBareNumerals:
    def test_a_figure_written_into_the_prose_is_refused(self):
        with pytest.raises(TemplateError, match="P1"):
            render("Revenue was $63.9 billion.\n", {})

    def test_the_finding_names_the_existing_class_a_rule(self):
        finding = bare_numeral_finding("Margin reached 41.2%.\n")
        assert finding.rule.id == "llm_computed_arithmetic"

    def test_a_slot_is_not_a_numeral(self):
        assert bare_numeral_finding("Revenue was {revenue}.\n") is None

    def test_a_year_in_prose_is_allowed(self):
        """claims.py already refuses to read a bare 2025 as a figure, and a
        draft has to be able to say which year it is talking about."""
        assert bare_numeral_finding("In the year ended 2025.\n") is None

    def test_the_finding_names_the_line(self):
        finding = bare_numeral_finding("Fine.\n\nBut 12.5% here.\n")
        assert "line 3" in finding.detail


# ---------------------------------------------------------------------------
# Refusals: the template and the evidence must agree exactly
# ---------------------------------------------------------------------------

class TestRefusals:
    def test_a_slot_with_no_figure_refuses(self):
        with pytest.raises(TemplateError, match="ebitda_margin"):
            render("Margin was {ebitda_margin}.\n", {"revenue": fig()})

    def test_a_figure_no_slot_cites_refuses(self):
        """A citation index carrying provenance nothing refers to makes a draft
        look better sourced than it is."""
        with pytest.raises(TemplateError, match="capex"):
            render("Revenue was {revenue}.\n",
                   {"revenue": fig(), "capex": fig("capex", body={
                       "cik": AVGO, "concept": "capex", "period_end": FY2025})})


# ---------------------------------------------------------------------------
# The rendered document
# ---------------------------------------------------------------------------

class TestRendering:
    def test_the_slot_becomes_the_figure_and_its_marker(self):
        drafted = render("Revenue was {revenue}.\n", {"revenue": fig()})
        assert f"Revenue was $63,887 million [^{fig().marker}]." in drafted.body

    def test_the_citation_index_is_emitted(self):
        md = render("Revenue was {revenue}.\n", {"revenue": fig()}).markdown()
        assert "## Citation index" in md
        assert "concept: revenue" in md

    def test_model_cells_are_emitted_only_when_there_are_some(self):
        md = render("Revenue was {revenue}.\n", {"revenue": fig()}).markdown()
        assert "## Model cells" not in md

    def test_a_model_figure_carries_its_declaration(self):
        cell = {"op": "ratio", "inputs": [], "unit": "pure"}
        gm = fig("gross_margin", kind=KIND_MODEL, text="67.77%",
                 body={"cell": "gross_margin"}, cell=cell)
        md = render("Gross margin was {gross_margin}.\n",
                    {"gross_margin": gm}).markdown()
        assert "## Model cells" in md and "gross_margin:" in md

    def test_the_emitted_index_parses_back(self):
        from src.qc.anchors import parse_index
        md = render("Revenue was {revenue}.\n", {"revenue": fig()}).markdown()
        parsed = parse_index(md)
        assert list(parsed) == [fig().marker]
        assert parsed[fig().marker].concept == "revenue"


# ---------------------------------------------------------------------------
# End to end, against AVGO as filed
# ---------------------------------------------------------------------------

def _loaded() -> bool:
    try:
        from src.facts.api import get_fact
        return get_fact(AVGO, "revenue", FY2025) is not None
    except Exception:
        return False


live = pytest.mark.skipif(not _loaded(), reason="AVGO facts not loaded")

TEMPLATE = """# Broadcom - Company Overview

**Conclusion.** Broadcom is two businesses of similar profit weight wearing one
semiconductor label. Semiconductor Solutions sells {semiconductor_solutions_revenue_share}
of the revenue and earns {semiconductor_solutions_profit_share} of the segment
profit, on a {semiconductor_solutions_margin} operating margin; Infrastructure
Software sells {infrastructure_software_revenue_share} and earns
{infrastructure_software_profit_share} on {infrastructure_software_margin}.
Nearly half the profit is enterprise software, so a comparison drawn against
semiconductor peers alone prices the smaller half of the earnings.

Revenue reached {revenue} against {revenue_prior} the year before, a
{revenue_growth} increase. Operating income of {operating_income} is
{operating_margin} of revenue and gross profit of {gross_profit} is
{gross_margin}. Research and development ran at {research_and_development}, or
{rd_intensity}, and share-based compensation of {share_based_compensation} is
{sbc_intensity} and a real cost against reported profit.

Operating cash flow of {operating_cash_flow} less capital expenditure of
{capex} leaves free cash flow of {free_cash_flow}, a {fcf_margin} margin, on
capital intensity of {capex_intensity}.

## Segment mix

{segment_mix}
"""


@live
class TestAgainstBroadcomAsFiled:
    def setup_method(self):
        from src.pitch.overview import Section1Evidence
        self.evidence = Section1Evidence.build(
            AVGO, FY2025, FY2024, gics="Semiconductors")
        self.figures = self.evidence.figures()

    def test_the_type_field_comes_out_contested(self):
        assert self.evidence.type_field.verdict == "contested"

    def test_the_segment_figures_match_the_filing(self):
        assert self.figures["semiconductor_solutions_revenue"].value == \
            Decimal("36858000000")
        assert self.figures["infrastructure_software_profit"].value == \
            Decimal("20765000000")

    def test_derived_figures_recompute_to_the_hand_checked_values(self):
        """43,294 / 63,887 = 67.77%; 10,977 / 63,887 = 17.18%."""
        assert self.figures["gross_margin"].text == "67.77%"
        assert self.figures["rd_intensity"].text == "17.18%"

    def _render(self):
        """The exhibit goes in as a BLOCK, not pre-substituted: it is Python
        output whose figures already carry their markers, and the P1 check must
        not mistake it for the LLM writing numbers."""
        table = self.evidence.segment_mix_table(self.figures)
        cited = {n: f for n, f in self.figures.items()
                 if f"{{{n}}}" in TEMPLATE or f"[^{f.marker}]" in table}
        return render(TEMPLATE, cited, blocks={"segment_mix": table},
                      cells=self.evidence.cells)

    def test_the_rendered_draft_passes_the_numeric_gate(self):
        """The whole point: a generated draft the QC layer accepts."""
        from src.qc.report import verify_draft
        report = verify_draft(self._render().markdown())
        assert report.failures == [], report.render()
        assert report.stale == [], report.render()
        assert report.passed, report.render()

    def test_the_rendered_draft_trips_no_prose_rule(self):
        from src.qc.anchors import parse_index
        from src.qc.claims import extract_claims
        from src.qc.prose_rules import prose_findings
        md = self._render().markdown()
        assert prose_findings(md, extract_claims(md), parse_index(md)) == []

    def test_every_figure_in_the_draft_resolves(self):
        from src.qc.report import verify_draft
        report = verify_draft(self._render().markdown())
        assert len(report.claims) >= 20
        assert all(r.ok for r in report.resolutions)
