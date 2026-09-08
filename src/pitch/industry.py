"""P3.5 — framework 2.4: the industry panel.

    "For every comp-set member, 3-5 years: revenue growth, gross / EBIT margin,
     ROIC, R&D and capex intensity, revenue share of panel."

Built on `panel.align`, and the alignment is the load-bearing part rather than
a preliminary. A panel that quietly put Microsoft's June year in the same column
as IBM's December one would look complete and be comparing different twelve-
month windows, which is exactly what 2.4 calls silent corruption. So the
excluded peers are returned WITH the panel, print WITH it, and a member that
appeared in neither list would be a silent drop.

Every figure is a model cell. Nothing is stored: `cells.py` recomputes from the
cited facts at verification time, so a panel figure carries the same provenance
a Section 1 figure does and passes the same gate.

ROIC is missing, deliberately
-----------------------------
2.4 asks for it and it is NOT here. ROIC needs invested capital, which needs
stockholders' equity, and `concept_map.yaml` maps no equity concept. The
available pieces -- long-term debt and cash -- give a denominator that is not
invested capital, and a plausible-looking ROIC on a wrong denominator is worse
than an absent one: it would be compared across the panel and believed. Adding
the concept is a reviewable change to the concept map, and until then the gap
is named here and in `MISSING_METRICS` rather than approximated.
"""
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from src.facts.api import Fact, get_series
from src.pitch.panel import Aligned, align, calendar_overlap_days
from src.qc.cells import CellError, CellRegistry
from src.valuation.comps import MINIMUM_COMP_SET

#: 2.4's metric list, as model-cell templates. `a` and `b` are concept names;
#: `prior` marks the input that comes from the preceding aligned year.
PANEL_METRICS: dict[str, dict] = {
    "revenue_growth": {"op": "growth", "a": "revenue", "b": "revenue",
                       "prior": "b"},
    "gross_margin": {"op": "ratio", "a": "gross_profit", "b": "revenue"},
    "ebit_margin": {"op": "ratio", "a": "operating_income", "b": "revenue"},
    "rd_intensity": {"op": "ratio", "a": "research_and_development",
                     "b": "revenue"},
    "capex_intensity": {"op": "ratio", "a": "capex", "b": "revenue"},
}

#: 2.4 metrics this panel cannot compute, and why. Named, never approximated.
MISSING_METRICS = {
    "roic": ("invested capital needs stockholders' equity, which "
             "concept_map.yaml does not map. Long-term debt and cash alone are "
             "not invested capital, and a plausible ROIC on a wrong "
             "denominator would be compared across the panel and believed"),
}

QUANTUM = "0.000001"


class PanelError(ValueError):
    """The panel cannot be built, and a thin one would be worse than none."""


@dataclass
class IndustryPanel:
    """One calendar column of 2.4's panel, and everyone who could not be in it."""

    calendar_year: int
    #: label -> the aligned annual period backing its column.
    aligned: dict[str, Aligned] = field(default_factory=dict)
    #: label -> why it is not in the panel. Never silently dropped.
    excluded: dict[str, str] = field(default_factory=dict)
    ciks: dict[str, int] = field(default_factory=dict)
    cells: dict[str, dict] = field(default_factory=dict)
    registry: CellRegistry | None = None
    revenues: dict[str, Fact] = field(default_factory=dict)

    @property
    def members(self) -> list[str]:
        return sorted(self.aligned)

    # -- construction -------------------------------------------------------
    @classmethod
    def build(cls, members: dict[str, int], calendar_year: int, *,
              as_of: date | None = None,
              minimum: int = MINIMUM_COMP_SET) -> "IndustryPanel":
        """Align every member to the calendar year, then declare its metrics."""
        periods: dict[str, tuple[date, date]] = {}
        series: dict[str, list[Fact]] = {}
        unavailable: dict[str, str] = {}

        for label, cik in members.items():
            facts = [f for f in get_series(cik, "revenue", years=6, as_of=as_of)
                     if f.period_start]
            if not facts:
                unavailable[label] = "no annual revenue series in the facts table"
                continue
            series[label] = facts
            best = max(
                ((calendar_overlap_days(f.period_start, f.period_end,
                                        calendar_year), f) for f in facts),
                key=lambda pair: pair[0])
            periods[label] = (best[1].period_start, best[1].period_end)

        aligned, excluded = align(periods, calendar_year)
        excluded |= unavailable

        if len(aligned) < minimum:
            raise PanelError(
                f"only {len(aligned)} member(s) aligned to CY{calendar_year}, "
                f"below the minimum comp set of {minimum}. Excluded: "
                f"{excluded}. Framework 4.8: n=2 is a teaching example, not a "
                f"valuation, and a thin panel reported as a comp set is worse "
                f"than none")

        panel = cls(calendar_year=calendar_year, aligned=aligned,
                    excluded=excluded, ciks={l: members[l] for l in aligned})

        for label in aligned:
            current = next(f for f in series[label]
                           if f.period_end == aligned[label].end)
            panel.revenues[label] = current
            prior = _prior_period(series[label], current)
            panel.cells |= _member_cells(label, members[label], current, prior)

        panel.cells["panel_revenue"] = {
            "op": "sum", "unit": "USD",
            "inputs": [_ref(panel.ciks[l], "revenue", panel.revenues[l].period_end)
                       for l in panel.members]}
        for label in panel.members:
            panel.cells[f"{label}_revenue_share"] = {
                "op": "ratio", "unit": "pure", "quantize": QUANTUM,
                "inputs": [_ref(panel.ciks[label], "revenue",
                                panel.revenues[label].period_end),
                           {"cell": "panel_revenue"}]}

        panel.registry = CellRegistry(declarations=panel.cells, as_of=as_of)
        return panel

    # -- reading it ---------------------------------------------------------
    def metrics(self, label: str) -> dict[str, Decimal]:
        """Every 2.4 metric this member can answer, recomputed.

        A metric is absent when the filer does not report an input for it --
        `CellError` naming the missing fact. Only that is swallowed, and it
        surfaces as `n/a` in the rendered panel and in `unavailable()` rather
        than as a silent hole. Any other failure propagates: a bug in the
        arithmetic must not be indistinguishable from a filer's disclosure
        choice.
        """
        out: dict[str, Decimal] = {}
        for metric in PANEL_METRICS:
            name = f"{label}_{metric}"
            if name not in self.cells:
                continue
            try:
                out[metric] = self.registry.compute(name).value
            except CellError:
                continue
        return out

    def unavailable(self, label: str) -> dict[str, str]:
        """Metrics this member cannot answer, with the missing input named."""
        out: dict[str, str] = {}
        for metric in PANEL_METRICS:
            name = f"{label}_{metric}"
            if name not in self.cells:
                out[metric] = "no prior aligned period for a growth rate"
                continue
            try:
                self.registry.compute(name)
            except CellError as exc:
                out[metric] = str(exc)
        return out

    def revenue_share(self, label: str) -> Decimal:
        return self.registry.compute(f"{label}_revenue_share").value

    def citation(self, label: str, metric: str) -> str:
        return self.registry.compute(f"{label}_{metric}").citation

    def render(self) -> str:
        cols = list(PANEL_METRICS)
        head = f"{'member':<8}{'share':>9}" + "".join(f"{c[:11]:>13}" for c in cols)
        lines = [f"Industry panel CY{self.calendar_year} "
                 f"({len(self.members)} aligned, {len(self.excluded)} excluded)",
                 head, "-" * len(head)]
        for label in self.members:
            m = self.metrics(label)
            row = f"{label:<8}{self.revenue_share(label):>8.1%} "
            row += "".join(f"{m[c]:>12.1%} " if c in m else f"{'n/a':>12} "
                           for c in cols)
            lines.append(row.rstrip())
        for label, why in sorted(self.excluded.items()):
            lines.append(f"{label:<8} EXCLUDED  {why}")
        for metric, why in MISSING_METRICS.items():
            lines.append(f"{'':<8} NOT COMPUTED  {metric}: {why}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------

def _ref(cik: int, concept: str, period_end: date) -> dict:
    return {"cik": cik, "concept": concept, "period_end": period_end,
            "segments": {}}


def _prior_period(series: list[Fact], current: Fact) -> Fact | None:
    """The aligned year before this one, for a growth rate.

    The series is newest first, so the prior period is simply the next entry
    whose end precedes the current one. It is NOT required to align to the
    previous calendar year: a growth rate compares a filer against itself, and
    a filer is always on its own fiscal calendar.
    """
    earlier = [f for f in series if f.period_end < current.period_end]
    return earlier[0] if earlier else None


def _member_cells(label: str, cik: int, current: Fact,
                  prior: Fact | None) -> dict[str, dict]:
    cells: dict[str, dict] = {}
    for metric, spec in PANEL_METRICS.items():
        if spec.get("prior") and prior is None:
            continue
        a = _ref(cik, spec["a"], current.period_end)
        b = (_ref(cik, spec["b"], prior.period_end) if spec.get("prior") == "b"
             else _ref(cik, spec["b"], current.period_end))
        cells[f"{label}_{metric}"] = {
            "op": spec["op"], "unit": "pure", "quantize": QUANTUM,
            "inputs": [a, b]}
    return cells
