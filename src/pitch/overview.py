"""P3.3 — framework 1: the Section 1 evidence set, and the figures it offers.

Everything a company overview may state as a number, computed in Python from
cited facts, and offered to the prose as named slots. The LLM chooses which of
these to use and what to say around them (1.4a, the judgment layer); it never
supplies one.

Three sources, and no fourth:

  * consolidated facts straight from the facts table (1.3);
  * derived figures as model cells, recomputed at verification time (6.4);
  * the segment panel, through `TypeField`, which is where 1.4h and the 1.5
    revenue-and-profit mix exhibit both come from.

The KPI snapshot 1.5 requires comes from the section 7 taxonomy rather than
from a second list maintained here -- `kpi.declarations_for` already turns a
sub-group into model cells, and a KPI that is disclosed in prose has no figure
to offer until a filing_text_disclosure record supplies one.

Naming: a slot is named for what it MEANS, not for the tag underneath it, so
prose reads `{semis_margin}` rather than `{avgo_operating_income_segment_ratio}`.
The mapping from meaning to provenance lives here, in one place, where it can
be read against the filing.
"""
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from src.facts.api import (Fact, SegmentPanel, get_fact, get_segment_panel,
                          get_series, pretty_member)
from src.pitch.draft import Figure
from src.pitch.kpi import DERIVED, declarations_for, sub_group
from src.pitch.types import TypeField
from src.qc.anchors import KIND_FACT, KIND_MODEL
from src.qc.cells import CellRegistry

MILLION = Decimal("1e6")

#: Consolidated facts a company overview is entitled to state directly.
CONSOLIDATED = (
    "revenue", "operating_income", "gross_profit", "research_and_development",
    "share_based_compensation", "operating_cash_flow", "capex",
)


class EvidenceError(ValueError):
    """The evidence set cannot be built for this filer and period."""


# ---------------------------------------------------------------------------
# Rendering a Decimal the way a pitch writes it
# ---------------------------------------------------------------------------

def usd_millions(value: Decimal) -> str:
    """'$63,887 million'. The scale word is what makes the figure resolvable:
    claims.py reads it, and a bare column of thousands is `scale_undeclared`."""
    return f"${(value / MILLION).quantize(Decimal(1)):,} million"


def percent(value: Decimal, places: str = "0.01") -> str:
    return f"{(value * 100).quantize(Decimal(places))}%"


def days(value: Decimal) -> str:
    return f"{value.quantize(Decimal('0.01'))} days"


def _fact_figure(name: str, fact: Fact, cik: int) -> Figure:
    body = {"cik": cik, "concept": fact.concept, "period_end": fact.period_end}
    if fact.segments:
        body["segments"] = dict(fact.segments)
    return Figure(name=name, text=usd_millions(fact.value), kind=KIND_FACT,
                  body=body, value=fact.value)


# ---------------------------------------------------------------------------

@dataclass
class Section1Evidence:
    """Framework 1.3 extraction plus 1.4h, for one filer and one period."""

    cik: int
    period_end: date
    prior_period_end: date
    panel: SegmentPanel
    type_field: TypeField
    facts: dict[str, Fact] = field(default_factory=dict)
    cells: dict[str, dict] = field(default_factory=dict)
    registry: CellRegistry | None = None
    kpi_group: str | None = None
    #: Annual period ends, newest first, for the 1.5 margin history exhibit.
    history_periods: list[date] = field(default_factory=list)

    # -- construction -------------------------------------------------------
    @classmethod
    def build(cls, cik: int, period_end: date, prior_period_end: date, *,
              kpi_group: str | None = None, gics: str | None = None,
              as_of: date | None = None) -> "Section1Evidence":
        panel = get_segment_panel(cik, years=5, as_of=as_of)
        type_field = TypeField.from_panel(panel, period_end, gics=gics)

        facts: dict[str, Fact] = {}
        for concept_name in CONSOLIDATED:
            fact = get_fact(cik, concept_name, period_end, as_of=as_of)
            if fact is None:
                raise EvidenceError(
                    f"cik {cik} reports no {concept_name} for {period_end}. A "
                    f"company overview cannot narrate around a missing "
                    f"consolidated figure without asserting one")
            facts[concept_name] = fact
        prior = get_fact(cik, "revenue", prior_period_end, as_of=as_of)
        if prior is None:
            raise EvidenceError(
                f"cik {cik} reports no revenue for {prior_period_end}, so the "
                f"6.3 current-year comparative cannot be shown")
        facts["revenue_prior"] = prior

        history = [f.period_end for f in get_series(cik, "revenue", years=5,
                                                    as_of=as_of)]
        cells = _consolidated_cells(cik, period_end, prior_period_end)
        cells |= _margin_history_cells(cik, history)
        cells |= _segment_cells(cik, type_field)
        if kpi_group:
            cells |= declarations_for(kpi_group, cik,
                                      [period_end, prior_period_end])

        return cls(cik=cik, period_end=period_end,
                   prior_period_end=prior_period_end, panel=panel,
                   type_field=type_field, facts=facts, cells=cells,
                   registry=CellRegistry(declarations=cells, as_of=as_of),
                   kpi_group=kpi_group, history_periods=history)

    # -- the figures --------------------------------------------------------
    def figures(self) -> dict[str, Figure]:
        """Every number this section may state, keyed by slot name."""
        out: dict[str, Figure] = {}

        for name, fact in self.facts.items():
            out[name] = _fact_figure(name, fact, self.cik)

        for cell_name, decl in self.cells.items():
            result = self.registry.compute(cell_name)
            unit = decl.get("unit", "pure")
            text = (usd_millions(result.value) if unit == "USD"
                    else days(result.value) if unit == "days"
                    else percent(result.value))
            out[cell_name] = Figure(name=cell_name, text=text, kind=KIND_MODEL,
                                    body={"cell": cell_name}, cell=decl,
                                    value=result.value)

        for share in self.type_field.shares:
            slug = _slug(share.label)
            out[f"{slug}_revenue"] = _fact_figure(
                f"{slug}_revenue", share.revenue_fact, self.cik)
            out[f"{slug}_profit"] = _fact_figure(
                f"{slug}_profit", share.profit_fact, self.cik)

        return out

    # -- the 1.5 exhibit ----------------------------------------------------
    def segment_mix_table(self, figures: dict[str, Figure]) -> str:
        """1.5: revenue AND profit mix by segment. Both columns, always -- a
        revenue-only mix is what `segment_profit_missing` blocks."""
        lines = ["| Segment | Revenue ($m) | Operating profit ($m) | Margin (%) |",
                 "|---|---|---|---|"]
        for share in self.type_field.shares:
            slug = _slug(share.label)
            margin = figures[f"{slug}_margin"]
            lines.append(
                f"| {share.label} "
                f"| {_bare(figures[f'{slug}_revenue'])} "
                f"| {_bare(figures[f'{slug}_profit'])} "
                f"| {margin.rendered.replace('%', '')} |")
        for excluded in self.type_field.excluded:
            lines.append(f"| {excluded.label} | excluded | {excluded.reason} | |")
        return "\n".join(lines)


    # -- the other two 1.5 exhibits ----------------------------------------
    def margin_history_table(self, figures: dict[str, Figure]) -> str:
        """1.5: margin / incremental-margin history.

        1.4g asks the incremental margin to be TESTED against history rather
        than asserted -- the last dollar of revenue either carried a higher
        margin than the average or it did not, and eight to twelve quarters of
        that is the evidence. Annual here, because the facts table holds
        annual periods and 1.5's exhibit is a history, not a seasonality read.
        """
        years = [p for p in self.history_periods]
        head = f"| Year | Gross margin (%) | Operating margin (%) | Incremental margin (%) |"
        lines = [head, "|---|---|---|---|"]
        for period_end in years:
            slug = _period_slug(period_end)
            cells = [f"gross_margin_{slug}", f"operating_margin_{slug}",
                     f"incremental_margin_{slug}"]
            row = f"| {period_end} "
            for name in cells:
                fig = figures.get(name)
                row += f"| {fig.rendered.replace('%', '')} " if fig else "| n/a "
            lines.append(row + "|")
        return "\n".join(lines)

    def kpi_snapshot_table(self, figures: dict[str, Figure]) -> str:
        """1.5: the KPI snapshot, from the section 7 taxonomy.

        Only the DERIVED entries appear. A KPI the filer discloses in prose has
        no figure until a filing_text_disclosure record supplies one, and
        printing it as blank would read as "zero" rather than "not disclosed".
        """
        if not self.kpi_group:
            return "_No sector KPI group selected._"
        from src.pitch.kpi import sub_group
        group = sub_group(self.kpi_group)
        lines = [f"| KPI ({group.label}) | Value | Definition |", "|---|---|---|"]
        for kpi in group.kpis:
            fig = figures.get(kpi.name)
            if fig is None:
                continue
            lines.append(f"| {kpi.name} | {fig.rendered} | {kpi.definition} |")
        return "\n".join(lines)


def _period_slug(period_end: date) -> str:
    return f"fy{period_end.year}"


def _bare(figure: Figure) -> str:
    """A table cell under a '($m)' header: the header declares the scale, so
    the cell carries digits only. claims.py reads the header."""
    digits = (figure.value / MILLION).quantize(Decimal(1))
    return f"{digits:,} [^{figure.marker}]"


def _slug(label: str) -> str:
    return "".join(ch if ch.isalnum() else "_" for ch in label.lower()).strip("_")


def _ratio(cik: int, numerator: str, denominator: str, period_end: date,
           *, segments: dict | None = None) -> dict:
    def ref(concept_name: str) -> dict:
        entry = {"cik": cik, "concept": concept_name, "period_end": period_end}
        if segments:
            entry["segments"] = dict(segments)
        return entry
    return {"op": "ratio", "quantize": "0.000001", "unit": "pure",
            "inputs": [ref(numerator), ref(denominator)]}


def _consolidated_cells(cik: int, period_end: date, prior: date) -> dict[str, dict]:
    def ref(c, p=period_end):
        return _ref(cik, c, p)

    return {
        "operating_margin": _ratio(cik, "operating_income", "revenue", period_end),
        "gross_margin": _ratio(cik, "gross_profit", "revenue", period_end),
        "rd_intensity": _ratio(cik, "research_and_development", "revenue", period_end),
        "sbc_intensity": _ratio(cik, "share_based_compensation", "revenue", period_end),
        "capex_intensity": _ratio(cik, "capex", "revenue", period_end),
        "revenue_growth": {"op": "growth", "quantize": "0.000001", "unit": "pure",
                           "inputs": [ref("revenue"), ref("revenue", prior)]},
        "free_cash_flow": {"op": "difference", "unit": "USD",
                           "inputs": [ref("operating_cash_flow"), ref("capex")]},
        "fcf_margin": {"op": "ratio", "quantize": "0.000001", "unit": "pure",
                       "inputs": [{"cell": "free_cash_flow"}, ref("revenue")]},
    }


def _ref(cik: int, concept: str, period_end: date) -> dict:
    """A consolidated fact reference. Segments are absent, not empty: a
    consolidated figure is not a segment slice with nothing in it."""
    return {"cik": cik, "concept": concept, "period_end": period_end}


def _margin_history_cells(cik: int, periods: list[date]) -> dict[str, dict]:
    """Gross, operating and INCREMENTAL margin per year.

    Incremental margin is the margin on the last dollar of revenue: the change
    in operating income over the change in revenue. 1.4g wants it tested
    against history, and a year without a predecessor simply has none.
    """
    cells: dict[str, dict] = {}
    for i, period_end in enumerate(periods):
        slug = _period_slug(period_end)
        cells[f"gross_margin_{slug}"] = _ratio(cik, "gross_profit", "revenue",
                                               period_end)
        cells[f"operating_margin_{slug}"] = _ratio(cik, "operating_income",
                                                   "revenue", period_end)
        if i + 1 < len(periods):
            prior = periods[i + 1]
            cells[f"delta_operating_income_{slug}"] = {
                "op": "difference", "unit": "USD",
                "inputs": [_ref(cik, "operating_income", period_end),
                           _ref(cik, "operating_income", prior)]}
            cells[f"delta_revenue_{slug}"] = {
                "op": "difference", "unit": "USD",
                "inputs": [_ref(cik, "revenue", period_end),
                           _ref(cik, "revenue", prior)]}
            cells[f"incremental_margin_{slug}"] = {
                "op": "ratio", "quantize": "0.000001", "unit": "pure",
                "inputs": [{"cell": f"delta_operating_income_{slug}"},
                           {"cell": f"delta_revenue_{slug}"}]}
    return cells


def _segment_cells(cik: int, type_field: TypeField) -> dict[str, dict]:
    """Per-segment margin and share. The share denominator is a cell of its own
    because the segment total is not a fact -- the filer reports the parts."""
    period_end = type_field.period_end
    axis = "us-gaap:StatementBusinessSegmentsAxis"
    cells: dict[str, dict] = {
        "segment_profit_total": {
            "op": "sum", "unit": "USD",
            "inputs": [{"cik": cik, "concept": "operating_income",
                        "period_end": period_end, "segments": {axis: s.member}}
                       for s in type_field.shares]},
    }
    for share in type_field.shares:
        slug = _slug(share.label)
        seg = {axis: share.member}
        cells[f"{slug}_margin"] = _ratio(
            cik, "operating_income", "revenue", period_end, segments=seg)
        cells[f"{slug}_revenue_share"] = {
            "op": "ratio", "quantize": "0.000001", "unit": "pure",
            "inputs": [{"cik": cik, "concept": "revenue",
                        "period_end": period_end, "segments": seg},
                       {"cik": cik, "concept": "revenue", "period_end": period_end}]}
        cells[f"{slug}_profit_share"] = {
            "op": "ratio", "quantize": "0.000001", "unit": "pure",
            "inputs": [{"cik": cik, "concept": "operating_income",
                        "period_end": period_end, "segments": seg},
                       {"cell": "segment_profit_total"}]}
    return cells


def kpi_slots(group_key: str) -> tuple[str, ...]:
    """The derived KPI names a draft for this sub-group may cite."""
    return tuple(k.name for k in sub_group(group_key).kpis
                 if k.disclosure == DERIVED)


__all__ = ["Section1Evidence", "EvidenceError", "usd_millions", "percent",
           "days", "kpi_slots", "pretty_member"]
