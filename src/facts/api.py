"""Module 12 — the typed fact API. Every value arrives with its citation.

This is the only sanctioned way for the rest of the pipeline to obtain a number.
There is deliberately no function that returns a bare Decimal: a figure without
an (accession, tag, period, member) is untraceable, and framework P3 makes an
untraceable figure a build error rather than a style problem.

Tag resolution is by priority from config/concept_map.yaml, applied per period,
so a filer that switched tags mid-history resolves correctly and the tag that
was actually used is visible on each returned Fact.

as_of turns every query into a point-in-time query (Audit G6): pass a date and
you see only what had been filed by then, restatements included or excluded on
their own merits.

CLI:  python -m src.facts.api MSFT --concept revenue
      python -m src.facts.api MSFT --panel --years 5
"""
import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from src.db import get_conn
from src.facts.concepts import Concept, axis, concept, qualifier_axes

ANNUAL_MIN_DAYS, ANNUAL_MAX_DAYS = 350, 380


@dataclass(frozen=True)
class Fact:
    """A number and everything needed to defend it."""

    concept: str
    value: Decimal
    unit: str
    qname: str                    # the tag actually used
    period_type: str
    period_start: date | None
    period_end: date
    segments: dict[str, str]
    accession: str
    filed_date: date
    fy: int | None
    source: str

    @property
    def member(self) -> str | None:
        """The single dimension member, when the fact carries exactly one."""
        return next(iter(self.segments.values())) if len(self.segments) == 1 else None

    @property
    def citation(self) -> str:
        period = (f"{self.period_start}..{self.period_end}" if self.period_start
                  else str(self.period_end))
        cite = f"{self.accession} | {self.qname} | {period}"
        if self.segments:
            cite += " | " + ", ".join(f"{k}={v}" for k, v in sorted(self.segments.items()))
        return cite


def pretty_member(qname: str | None) -> str:
    """'msft:IntelligentCloudMember' -> 'Intelligent Cloud' (display only)."""
    if not qname:
        return "Consolidated"
    local = qname.split(":")[-1]
    local = re.sub(r"Member$", "", local)
    return re.sub(r"(?<!^)(?=[A-Z])", " ", local).replace("  ", " ").strip()


def _relation(as_of: date | None) -> tuple[str, dict]:
    return (("facts_asof(%(as_of)s)", {"as_of": as_of}) if as_of
            else ("facts_current", {}))


def _segment_sql(segments: dict | str | None) -> tuple[str, dict]:
    """None = any · {} = consolidated only · '<axis>' = carries that axis.

    Rows matched by the axis form are narrowed further in Python by
    is_segment_row(), which SQL cannot express readably.
    """
    if segments is None:
        return "", {}
    if segments == {}:
        return " AND segments = '{}'::jsonb", {}
    if isinstance(segments, str):
        return " AND segments ? %(axis)s", {"axis": segments}
    from psycopg.types.json import Jsonb
    return " AND segments = %(segments)s", {"segments": Jsonb(segments)}


def is_segment_row(segments: dict[str, str], ax: str,
                   qualifiers: dict[str, list[str]] | None = None) -> bool:
    """Is this fact a reportable-segment total on `ax`?

    Yes for the axis alone, and for the axis plus a qualifier axis at an allowed
    member (ASC 280's ConsolidationItemsAxis = OperatingSegmentsMember, which
    NVIDIA puts on every segment figure).

    No for the axis crossed with geography or product: that is a finer slice,
    and summing those would double-count against the consolidated total.
    """
    if ax not in segments:
        return False
    allowed = qualifier_axes() if qualifiers is None else qualifiers
    return all(k == ax or v in allowed.get(k, ()) for k, v in segments.items())


def latest_vintage(facts: list[Fact]) -> list[Fact]:
    """Keep, per period, only the segment rows from the most recent filing.

    Filers rename segment members: NVIDIA's FY2024 breakdown was filed under
    `nvda:ComputeAndNetworkingMember` and re-filed in FY2026 as
    `...ComputeAndNetworkingSegmentMember`. Both are current — different members
    are different facts, not restatements of one another — so a panel that
    merges the two vintages counts every NVIDIA segment twice.

    A period's breakdown therefore comes from ONE filing, the latest to report
    it, which is also the basis its consolidated total is stated on.
    """
    by_period: dict[date, list[Fact]] = {}
    for f in facts:
        by_period.setdefault(f.period_end, []).append(f)

    kept: list[Fact] = []
    for group in by_period.values():
        newest = max((f.filed_date, f.accession) for f in group)
        kept.extend(f for f in group if (f.filed_date, f.accession) == newest)
    return kept


def _fetch(cik: int, c: Concept, *, segments=None, as_of=None, annual=True,
           period_end: date | None = None) -> list[Fact]:
    rel, params = _relation(as_of)
    seg_sql, seg_params = _segment_sql(segments)
    params |= seg_params | {
        "cik": cik,
        "tags": [t.split(":", 1)[1] for t in c.tags],
        "taxonomies": sorted({t.split(":", 1)[0] for t in c.tags}),
        "unit": c.unit, "period_type": c.period_type,
    }

    sql = f"""
        SELECT taxonomy, tag, value, unit, period_type, period_start, period_end,
               segments, accession, filed_date, fy, source
        FROM {rel}
        WHERE cik = %(cik)s AND tag = ANY(%(tags)s) AND taxonomy = ANY(%(taxonomies)s)
          AND unit = %(unit)s AND period_type = %(period_type)s{seg_sql}
    """
    if annual and c.period_type == "duration":
        sql += (f" AND (period_end - period_start) BETWEEN {ANNUAL_MIN_DAYS}"
                f" AND {ANNUAL_MAX_DAYS}")
    if period_end:
        sql += " AND period_end = %(period_end)s"
        params["period_end"] = period_end

    with get_conn() as conn:
        rows = conn.execute(sql, params).fetchall()

    if isinstance(segments, str):
        rows = [r for r in rows if is_segment_row(r[7], segments)]

    priority = {t: i for i, t in enumerate(c.tags)}
    facts = [Fact(concept=c.name, value=r[2], unit=r[3], qname=f"{r[0]}:{r[1]}",
                  period_type=r[4], period_start=r[5], period_end=r[6],
                  segments=r[7], accession=r[8], filed_date=r[9], fy=r[10], source=r[11])
             for r in rows]

    # One winner per (period, segments): the highest-priority tag present.
    best: dict[tuple, Fact] = {}
    for f in facts:
        key = (f.period_start, f.period_end, tuple(sorted(f.segments.items())))
        prior = best.get(key)
        if prior is None or priority[f.qname] < priority[prior.qname]:
            best[key] = f
    return sorted(best.values(), key=lambda f: f.period_end, reverse=True)


def get_fact(cik: int, concept_name: str, period_end: date, *,
             segments=None, as_of: date | None = None) -> Fact | None:
    """One figure for one period, or None if the filer never reported it."""
    c = concept(concept_name, cik)
    hits = _fetch(cik, c, segments=segments if segments is not None else {},
                  as_of=as_of, period_end=period_end)
    return hits[0] if hits else None


def get_series(cik: int, concept_name: str, *, years: int = 5, annual: bool = True,
               segments=None, as_of: date | None = None) -> list[Fact]:
    """Consolidated history for one concept, newest first."""
    c = concept(concept_name, cik)
    hits = _fetch(cik, c, segments=segments if segments is not None else {},
                  as_of=as_of, annual=annual)
    return hits[:years]


@dataclass
class PanelCell:
    member: str
    facts: dict[str, Fact]

    def value(self, concept_name: str) -> Decimal | None:
        f = self.facts.get(concept_name)
        return f.value if f else None

    @property
    def margin(self) -> Decimal | None:
        """Operating margin, computed in Python — never by an LLM (Audit section 5)."""
        rev, op = self.value("revenue"), self.value("operating_income")
        if rev in (None, 0) or op is None:
            return None
        return (op / rev).quantize(Decimal("0.0001"))


@dataclass
class SegmentPanel:
    cik: int
    axis: str
    concepts: tuple[str, ...]
    periods: list[tuple[date, date]]              # newest first
    cells: dict[tuple[date, str], PanelCell]      # (period_end, member) -> cell
    consolidated: dict[tuple[date, str], Fact]    # (period_end, concept) -> fact

    def members(self) -> list[str]:
        seen: list[str] = []
        for (_, member) in self.cells:
            if member not in seen:
                seen.append(member)
        return seen

    def segment_sum(self, period_end: date, concept_name: str) -> Decimal | None:
        vals = [c.value(concept_name) for (pe, _), c in self.cells.items() if pe == period_end]
        vals = [v for v in vals if v is not None]
        return sum(vals) if vals else None

    def reconciles(self, period_end: date, concept_name: str = "revenue") -> bool | None:
        """Do the segments add up to the consolidated figure the filer reported?"""
        total = self.consolidated.get((period_end, concept_name))
        seg = self.segment_sum(period_end, concept_name)
        return None if total is None or seg is None else seg == total.value


def get_segment_panel(cik: int, *, concepts: tuple[str, ...] = ("revenue", "operating_income"),
                      years: int = 5, axis_name: str = "segment",
                      as_of: date | None = None) -> SegmentPanel:
    """Segment revenue AND operating profit by fiscal year — the Phase 0 exit query."""
    ax = axis(axis_name)
    cells: dict[tuple[date, str], PanelCell] = {}
    consolidated: dict[tuple[date, str], Fact] = {}
    periods: list[tuple[date, date]] = []

    for name in concepts:
        c = concept(name, cik)
        for f in latest_vintage(_fetch(cik, c, segments=ax, as_of=as_of)):
            member = f.segments[ax]
            cell = cells.setdefault((f.period_end, member),
                                    PanelCell(member=member, facts={}))
            cell.facts[name] = f
            if (f.period_start, f.period_end) not in periods:
                periods.append((f.period_start, f.period_end))
        for f in _fetch(cik, c, segments={}, as_of=as_of):
            consolidated[(f.period_end, name)] = f

    periods.sort(key=lambda p: p[1], reverse=True)
    periods = periods[:years]
    keep = {p[1] for p in periods}
    cells = {k: v for k, v in cells.items() if k[0] in keep}

    return SegmentPanel(cik=cik, axis=ax, concepts=tuple(concepts),
                        periods=periods, cells=cells, consolidated=consolidated)


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("ticker")
    ap.add_argument("--concept", default="revenue")
    ap.add_argument("--panel", action="store_true")
    ap.add_argument("--years", type=int, default=5)
    ap.add_argument("--as-of", help="point-in-time: only data filed on or before YYYY-MM-DD")
    a = ap.parse_args()

    as_of = date.fromisoformat(a.as_of) if a.as_of else None
    with get_conn() as conn:
        cik = conn.execute("SELECT cik FROM companies WHERE ticker = %s",
                           (a.ticker.upper(),)).fetchone()[0]

    if a.panel:
        panel = get_segment_panel(cik, years=a.years, as_of=as_of)
        for _, period_end in panel.periods:
            print(f"\n{period_end}")
            for member in panel.members():
                cell = panel.cells.get((period_end, member))
                if not cell:
                    continue
                rev, op, m = cell.value("revenue"), cell.value("operating_income"), cell.margin
                print(f"  {pretty_member(member):<34} {rev or 0:>18,} {op or 0:>18,} "
                      f"{'' if m is None else f'{m:>8.1%}'}")
            print(f"  {'segments sum':<34} {panel.segment_sum(period_end, 'revenue') or 0:>18,}"
                  f"   reconciles={panel.reconciles(period_end)}")
    else:
        for f in get_series(cik, a.concept, years=a.years, as_of=as_of):
            print(f"  {f.period_end}  {f.value:>20,} {f.unit:<10}  {f.citation}")
