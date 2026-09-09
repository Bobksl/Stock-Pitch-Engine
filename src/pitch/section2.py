"""P3.8 — framework 2: the Section 2 evidence set and its 2.6 exhibits.

    2.6: "~400-500 words, conclusion first. Exhibits: industry panel;
     relative-growth / share chart; peer drawdown table. Explicit stance on
     structure and direction."

Assembles what the earlier modules already produce rather than recomputing any
of it: the approved comp set (2.3), the calendar-aligned industry panel (2.4)
with its named exclusions, and the peer drawdown table (2.4 / 2.5i) whose
statistics are series model cells recomputed at verification time (6.4, v1.5).

Every figure here is a model cell, so a Section 2 number carries the same
provenance a Section 1 number does and passes the same gate. Nothing in this
module produces a value; it declares cells and lays them out.

The relative-growth exhibit is 2.5h
-----------------------------------
"Company growth minus peer-median growth, per year. Sustained positive = share
gain; pair with relative margin to see whether it's bought with price." It is
computed here and NOT cached into the primer: it is a statement about one
company, and 2.8's primer refuses to carry it for that reason.
"""
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from src.pitch.compset import CompSet
from src.pitch.draft import Figure
from src.pitch.drawdown import StressWindow, stress_windows
from src.pitch.industry import IndustryPanel
from src.pitch.overview import percent
from src.qc.anchors import KIND_MODEL
from src.qc.cells import CellError, CellRegistry

#: The instrument stress windows are derived from. 2.5i calls peer drawdown
#: "the first place market data enters"; this is the market it enters from.
DEFAULT_BENCHMARK = "SPY"


class Section2Error(ValueError):
    """Section 2 cannot be assembled from this evidence."""


@dataclass
class Section2Evidence:
    """2.3 comp set + 2.4 panel + 2.4/2.5i drawdown, as declared cells."""

    comp_set: CompSet
    panel: IndustryPanel
    windows: list[StressWindow] = field(default_factory=list)
    benchmark: str = DEFAULT_BENCHMARK
    cells: dict[str, dict] = field(default_factory=dict)
    registry: CellRegistry | None = None
    #: label -> why it has no drawdown row. Never silently absent.
    drawdown_gaps: dict[str, str] = field(default_factory=dict)
    #: The company being pitched. In the panel, not in the comp set.
    target: str | None = None

    @classmethod
    def build(cls, comp_set: CompSet, calendar_year: int, *,
              target: tuple[str, int] | None = None,
              benchmark: str = DEFAULT_BENCHMARK,
              price_start: date | None = None,
              price_end: date | None = None,
              as_of: date | None = None) -> "Section2Evidence":
        # The TARGET belongs in the panel alongside its comp set. 2.4 asks for
        # "revenue share of panel", which is meaningless with the subject of
        # the pitch left out of the denominator, and every relative-growth
        # reading in 2.5h is the target measured against the rest. The comp set
        # is the peers; the panel is the peers AND the company being pitched.
        members = dict(comp_set.panel_members())
        if target:
            members[target[0]] = target[1]
        panel = IndustryPanel.build(members, calendar_year, as_of=as_of)

        from src.ingest.prices import get_closes
        start = price_start or date(2000, 1, 1)
        end = price_end or date.today()
        bench_series = get_closes(benchmark, start, end)
        if not bench_series:
            raise Section2Error(
                f"no prices for the benchmark {benchmark!r} between {start} and "
                f"{end}. 2.4 defines stress windows from a benchmark decline, "
                f"so without it there are no windows to measure peers over")
        windows = stress_windows(bench_series)

        cells = _relative_growth_cells(panel)
        cells |= _drawdown_cells(panel.members, windows, benchmark)

        return cls(comp_set=comp_set, panel=panel, windows=windows,
                   benchmark=benchmark, cells=cells, target=target[0] if target else None,
                   registry=CellRegistry(declarations=cells, as_of=as_of))

    # -- figures ------------------------------------------------------------
    def figures(self) -> dict[str, Figure]:
        """Every Section 2 number, keyed by slot name. Panel figures come from
        the panel's own registry so a figure is declared exactly once."""
        out: dict[str, Figure] = {}
        for name, decl in self.panel.cells.items():
            try:
                value = self.panel.registry.compute(name).value
            except CellError:
                continue
            out[name] = _figure(name, value, decl, self.panel.cells)

        for name, decl in self.cells.items():
            try:
                value = self.registry.compute(name).value
            except CellError as exc:
                self.drawdown_gaps[name] = str(exc)
                continue
            out[name] = _figure(name, value, decl, self.cells)
        return out

    # -- the 2.6 exhibits ---------------------------------------------------
    def industry_panel_table(self, figures: dict[str, Figure]) -> str:
        cols = ["revenue_growth", "gross_margin", "ebit_margin",
                "rd_intensity", "capex_intensity"]
        head = ("| Member | Revenue share (%) | Revenue growth (%) | "
                "Gross margin (%) | EBIT margin (%) | R&D (%) | Capex (%) |")
        lines = [head, "|---|---|---|---|---|---|---|"]
        for label in self.panel.members:
            row = f"| {label} | {_pct_cell(figures, f'{label}_revenue_share')} "
            row += "".join(f"| {_pct_cell(figures, f'{label}_{c}')} " for c in cols)
            lines.append(row + "|")
        # An excluded peer is named by its FISCAL PERIOD, not by a day count.
        # Dates are masked by claims.py; a day count is a numeral, and an
        # unanchored numeral is a figure with no provenance -- which the gate
        # blocks even when it is metadata about how the panel was built. The
        # arithmetic stays in `panel.excluded` for the CLI and the logs.
        for label in sorted(self.panel.excluded):
            period = self.panel.considered.get(label)
            span = (f"fiscal year {period[0]}..{period[1]}" if period
                    else "no annual series")
            lines.append(
                f"| {label} | EXCLUDED | {span} does not align to the calendar "
                f"column (§2.4) | | | | |")
        return "\n".join(lines)

    def relative_growth_table(self, figures: dict[str, Figure]) -> str:
        """2.5h: company growth minus peer-median growth, and relative margin.

        Paired deliberately. Sustained positive relative growth is share gain;
        read beside relative margin it says whether the share was bought with
        price, which the growth line alone cannot.
        """
        lines = ["| Member | Growth vs peer median (pp) | EBIT margin vs peer "
                 "median (pp) |", "|---|---|---|"]
        for label in self.panel.members:
            lines.append(
                f"| {label} | {_pct_cell(figures, f'{label}_relative_growth')} "
                f"| {_pct_cell(figures, f'{label}_relative_margin')} |")
        return "\n".join(lines)

    def drawdown_table(self, figures: dict[str, Figure], window_index: int = 0
                       ) -> str:
        """2.6's peer drawdown table for one stress window.

        A statistic that cannot be computed shows as `not recovered` or `n/a`
        with the peer still in the table. An absent number and a dropped peer
        read very differently in a ranking, and 2.5i is read as a ranking.
        """
        if not self.windows:
            return "_No benchmark stress window of the required depth._"
        window = self.windows[window_index]
        slug = _window_slug(window)
        bench = figures.get(f"benchmark_dd_{slug}")
        depth = bench.rendered if bench else "(benchmark depth unavailable)"
        lines = [f"Stress window {window.peak} to {window.trough}, benchmark "
                 f"{depth}:", "",
                 "| Peer | Drawdown (%) | Recovery (days) | Downside capture (x) "
                 "| Correlation (ratio) | Beta (ratio) |", "|---|---|---|---|---|---|"]
        for label in self.panel.members:
            cells = [f"{label}_dd_{slug}", f"{label}_rec_{slug}",
                     f"{label}_cap_{slug}", f"{label}_corr_{slug}",
                     f"{label}_beta_{slug}"]
            row = f"| {label} "
            for i, name in enumerate(cells):
                fig = figures.get(name)
                if fig is None:
                    row += "| not recovered " if i == 1 else "| n/a "
                else:
                    row += f"| {fig.rendered.replace('%', '')} "
            lines.append(row + "|")
        return "\n".join(lines)


# ---------------------------------------------------------------------------

def _figure(name: str, value: Decimal, decl: dict, cells: dict) -> Figure:
    """Render a cell for the prose.

    `unit` is PROVENANCE -- what resolve.py compares the claim against -- and
    `display` is presentation. They are separate keys because a downside
    capture and a gross margin are both dimensionless (`pure`) and must not be
    written the same way: multiplying a capture of 2.52 by a hundred is how
    "252.26" ends up in a table under a column headed (x).
    """
    display = decl.get("display") or ("percent" if decl.get("unit", "pure") == "pure"
                                      else decl.get("unit"))
    if display == "ratio":
        text = str(value.quantize(Decimal("0.01")))
    elif display == "days":
        text = str(value.quantize(Decimal(1)))
    else:
        text = percent(value)
    return Figure(name=name, text=text, kind=KIND_MODEL, body={"cell": name},
                  cell=decl, value=value)


def _pct_cell(figures: dict[str, Figure], name: str) -> str:
    fig = figures.get(name)
    return fig.rendered.replace("%", "") if fig else "n/a"


def _window_slug(window: StressWindow) -> str:
    return f"{window.peak:%Y%m%d}"


def _relative_growth_cells(panel: IndustryPanel) -> dict[str, dict]:
    """2.5h, as cells: each member's growth and margin less the peer median.

    The median is a literal input carrying its own note, because `cells.py` has
    no median op and adding one for a value computed over the panel would put
    the panel's membership inside the cell vocabulary. The note names the
    members it was taken over, so the figure still says where it came from.
    """
    cells: dict[str, dict] = {}
    for metric, short in (("revenue_growth", "growth"), ("ebit_margin", "margin")):
        values = []
        for label in panel.members:
            got = panel.metrics(label).get(metric)
            if got is not None:
                values.append(got)
        if not values:
            continue
        median = _median(values)
        note = (f"median {metric} across the {len(values)} panel member(s) "
                f"reporting it: {', '.join(sorted(panel.members))}")
        for label in panel.members:
            if metric not in panel.metrics(label):
                continue
            cells[f"{label}_relative_{short}"] = {
                "op": "difference", "unit": "pure", "quantize": "0.000001",
                "inputs": [{"cell": f"{label}_{metric}"},
                           {"literal": str(median), "note": note}]}
            cells[f"{label}_{metric}"] = panel.cells[f"{label}_{metric}"]
    return cells


def _median(values: list[Decimal]) -> Decimal:
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2


def _drawdown_cells(members: list[str], windows: list[StressWindow],
                    benchmark: str) -> dict[str, dict]:
    """2.4's five statistics per peer per window, as series cells (6.4, v1.5).

    The drawdown, correlation and beta are measured over the whole window --
    peak to recovery, or to the end of the data when it has not recovered --
    and the downside capture over the falling LEG only, peak to trough. A
    capture measured across a recovery would net the rebound against the fall
    and report a peer as defensive because it bounced.
    """
    cells: dict[str, dict] = {}
    for window in windows:
        slug = _window_slug(window)
        end = window.recovered or date.today()
        full = {"from": window.peak, "to": end}
        leg = {"from": window.peak, "to": window.trough}
        # Recovery runs to the END OF THE DATA, not to the benchmark's own
        # recovery date. How long a peer took to regain its peak is a property
        # of that peer; bounding it at the market's recovery reports anyone
        # slower than the market as never having recovered. AMD took 459 days
        # and MRVL 671 from the 2022 trough, both past the benchmark's
        # 2023-12-13, and both read as "not recovered" until this was split out.
        recovery_window = {"from": window.peak, "to": date.today()}
        bench_full = {"series": benchmark, **full}
        bench_leg = {"series": benchmark, **leg}
        # The window's own depth is a FIGURE and gets provenance like any
        # other. Writing it into the caption from the StressWindow object
        # would put a number in the draft that no anchor stands behind, which
        # the gate catches and should.
        cells[f"benchmark_dd_{slug}"] = {
            "op": "max_drawdown", "unit": "pure", "quantize": "0.000001",
            "inputs": [{"series": benchmark, **leg}]}
        for label in members:
            cells[f"{label}_dd_{slug}"] = {
                "op": "max_drawdown", "unit": "pure", "quantize": "0.000001",
                "inputs": [{"series": label, **full}]}
            cells[f"{label}_rec_{slug}"] = {
                "op": "recovery_days", "unit": "pure", "display": "days",
                "inputs": [{"series": label, **full},
                           {"series": label, **recovery_window}]}
            cells[f"{label}_cap_{slug}"] = {
                "op": "downside_capture", "unit": "pure", "display": "ratio", "quantize": "0.0001",
                "inputs": [{"series": label, **leg}, bench_leg]}
            cells[f"{label}_corr_{slug}"] = {
                "op": "correlation", "unit": "pure", "display": "ratio", "quantize": "0.0001",
                "inputs": [{"series": label, **full}, bench_full]}
            cells[f"{label}_beta_{slug}"] = {
                "op": "stress_beta", "unit": "pure", "display": "ratio", "quantize": "0.0001",
                "inputs": [{"series": label, **full}, bench_full]}
    return cells
