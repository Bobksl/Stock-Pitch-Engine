"""P1.3 — C12 staleness and the comparative rule (framework 6.3, 1.6).

    "Every figure from the latest filed period. Any prior-year figure must
     appear alongside its current-year comparative."

Read literally that first sentence bans a five-year revenue history, which the
framework requires elsewhere (1.5 mandates margin history exhibits). The second
sentence is what resolves it: prior-period figures are legal *accompanied*. So
this is a rule about the SET of claims in a draft, not about each claim alone,
and it cannot be checked one figure at a time.

Claims are therefore grouped by what they are a figure OF -- (cik, concept,
segments) -- and each group is checked as a unit:

  * the latest period available for that series must appear in the group;
  * any older period is then legal, because its comparative is present;
  * an older period alone is stale and fails.

"Latest available" comes from the facts table, never from the draft. A draft
that consistently quotes FY2024 would otherwise certify itself as current. With
`--as-of` the latest available period is the latest FILED BY THEN, which is what
makes a backtested pitch (Audit G6) check against what the market actually knew
rather than against today's table.

Only fact-anchored claims participate. A model cell's periods live in its
inputs, and an external record carries its own as-of date and is governed by the
source's release calendar rather than by EDGAR's.

Periodicity, and why instants needed stating separately (spec 6.3, v1.4)
------------------------------------------------------------------------
"Latest available" is measured at the periodicity the draft is written at. For
a DURATION concept that already held without anyone writing it down, because
`get_series` filters durations to annual lengths, so the latest revenue is the
latest fiscal year rather than the latest quarter.

Instants had no such filter, and the asymmetry was invisible until a draft
first cited one. `companyfacts` carries every balance the filer has published,
so the newest inventory or RPO instant is a recent QUARTER end. Measured
against that, Broadcom's FY2025 remaining performance obligation is stale --
and the only way to satisfy the rule would be to quote the Q2-2026 balance
inside an annual overview, mixing periods rather than refreshing them. That is
the cross-sectional corruption 2.4 forbids, arriving down the time axis instead
of across peers.

So an instant is compared against the latest instant at an ANNUAL REPORTING
DATE, taken from the filer's own annual filings rather than inferred from the
shape of the dates.
"""
from dataclasses import dataclass, field
from datetime import date

from src.db import get_conn
from src.facts.api import get_series
from src.facts.concepts import ConceptError, concept
from src.qc.anchors import KIND_FACT, Anchor
from src.qc.claims import NumericClaim
from src.qc.resolve import Resolution

STALE = "stale_period"
NO_SERIES = "no_series"

#: Forms whose period_end is an annual reporting date. A balance-sheet instant
#: in an annual draft is quoted at one of these.
ANNUAL_FORMS = ("10-K", "10-K/A", "10-KT", "20-F", "40-F")

#: get_series slices to `years`; instants carry no annual filter, so ask for
#: enough history that the annual dates among them are certain to be included.
_INSTANT_LOOKBACK = 1000


@dataclass(frozen=True)
class SeriesKey:
    """What a figure is a figure OF: one concept, one entity, one slice."""

    cik: int
    concept: str
    segments: tuple[tuple[str, str], ...]

    @classmethod
    def of(cls, anchor: Anchor) -> "SeriesKey":
        return cls(cik=anchor.cik, concept=anchor.concept,
                   segments=tuple(sorted(anchor.segments.items())))

    def describe(self) -> str:
        seg = ", ".join(f"{k}={v}" for k, v in self.segments)
        return f"{self.concept} (cik {self.cik}{', ' + seg if seg else ''})"


@dataclass
class SeriesFinding:
    """One series' recency verdict and the claims that produced it."""

    key: SeriesKey
    latest_available: date | None
    periods_claimed: set[date] = field(default_factory=set)
    stale: list[tuple[NumericClaim, date]] = field(default_factory=list)
    status: str = "ok"
    detail: str = ""

    @property
    def ok(self) -> bool:
        return self.status == "ok"


def _is_instant(concept_name: str, cik: int) -> bool:
    try:
        return concept(concept_name, cik).period_type == "instant"
    except (ConceptError, KeyError):
        return False


def _annual_period_ends(cik: int, as_of: date | None) -> set[date]:
    """The filer's own annual reporting dates, from its annual filings.

    Read from `filings` rather than inferred from the dates themselves: a
    fiscal year ending on the Sunday nearest 31 October moves by a few days
    each year, and any rule guessing which instants are "annual-looking" would
    have to encode that. The filer already told us, once per 10-K.
    """
    sql = ("SELECT DISTINCT period_end FROM filings "
           "WHERE cik = %(cik)s AND form = ANY(%(forms)s) "
           "AND period_end IS NOT NULL")
    params: dict = {"cik": cik, "forms": list(ANNUAL_FORMS)}
    if as_of:
        sql += " AND filed_date <= %(as_of)s"
        params["as_of"] = as_of
    with get_conn() as conn:
        return {row[0] for row in conn.execute(sql, params).fetchall()}


def _latest_available(key: SeriesKey, as_of: date | None) -> date | None:
    """The most recent period the facts table can answer, at the draft's periodicity.

    Spec 6.3 (v1.4). For a duration the facts API has already restricted the
    series to annual lengths. For an instant it has not, so the annual dates
    are applied here; if the filer has no annual filing on record the plain
    latest stands, because inventing a periodicity would be worse than
    reporting the newest thing we have.
    """
    segments = dict(key.segments) if key.segments else {}
    if not _is_instant(key.concept, key.cik):
        series = get_series(key.cik, key.concept, years=1, segments=segments,
                            as_of=as_of)
        return series[0].period_end if series else None

    series = get_series(key.cik, key.concept, years=_INSTANT_LOOKBACK,
                        segments=segments, as_of=as_of)
    if not series:
        return None
    annual = _annual_period_ends(key.cik, as_of)
    at_year_end = [f.period_end for f in series if f.period_end in annual]
    return max(at_year_end) if at_year_end else series[0].period_end


def check_recency(resolutions: list[Resolution], index: dict[str, Anchor], *,
                  as_of: date | None = None) -> list[SeriesFinding]:
    """C12 over a whole draft, one finding per fact-anchored series.

    Runs on RESOLVED claims only: a figure that failed P1.2 already blocks
    publication, and reporting it a second time as stale would bury the real
    finding under a derived one.
    """
    groups: dict[SeriesKey, list[tuple[NumericClaim, date]]] = {}
    for res in resolutions:
        if not res.ok or res.claim.anchor is None:
            continue
        anchor = index.get(res.claim.anchor)
        if anchor is None or anchor.kind != KIND_FACT:
            continue
        groups.setdefault(SeriesKey.of(anchor), []).append(
            (res.claim, anchor.period_end))

    findings: list[SeriesFinding] = []
    for key, entries in groups.items():
        latest = _latest_available(key, as_of)
        finding = SeriesFinding(key=key, latest_available=latest,
                                periods_claimed={p for _, p in entries})

        if latest is None:
            finding.status = NO_SERIES
            finding.detail = (f"no series for {key.describe()}, so the latest "
                              f"filed period cannot be established")
        elif latest not in finding.periods_claimed:
            finding.status = STALE
            finding.stale = [(c, p) for c, p in entries if p != latest]
            quoted = ", ".join(str(p) for p in sorted(finding.periods_claimed))
            finding.detail = (
                f"{key.describe()} is quoted for {quoted} but the latest filed "
                f"period is {latest}. Framework 6.3: every figure comes from the "
                f"latest filed period, and a prior-year figure is only admissible "
                f"alongside its current-year comparative.")
        findings.append(finding)

    return findings
