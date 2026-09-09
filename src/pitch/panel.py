"""P3.5 — framework 2.4 period alignment: which peers may share a panel column.

2.4 is unusually specific, and it is the mechanism 4.8's "same calendar period
across all peers" is enforced by:

    Periods are stored exactly as reported. A calendar mapping is derived
    separately, following the SEC frames convention. The tolerance window of
    that convention is documented in code, because it determines whether an
    off-cycle peer is EXCLUDED from a panel or MIS-ASSIGNED to a calendar
    period -- and the latter silently corrupts every cross-sectional comparison
    built on the panel. Exclusion is the default; mis-assignment is never
    acceptable.

Two questions, and SEC answers only one
---------------------------------------
"Is this an annual period?" is answered by the SEC frames documentation, which
states an annual frame as **365 days plus or minus 30** (and a quarter as 91
plus or minus 30):

    https://www.sec.gov/search-filings/edgar-application-programming-interfaces

"Which calendar year is it?" is NOT answered there. The documentation says only
that frames are "assembled by the dates that best align with a calendar quarter
or year", and cautions that a frame legitimately contains facts with different
start and end dates. No assignment tolerance is published, and inventing one
and attributing it to SEC would be worse than owning it.

So the assignment measure is stated here and owned here: **days of the fiscal
period that fall inside the calendar year**. That is a direct reading of "best
align", it is computable from the two dates alone, and it is legible -- 306 of
365 days says plainly how much of Broadcom's FY2025 is really 2025, in a way
that "59 days off" does not.

`ANNUAL_TOLERANCE_DAYS` is SEC's and is cited. `DEFAULT_MIN_OVERLAP_DAYS` is
this project's and is argued below. Do not confuse them: they answer different
questions and only one has an authority behind it.

Not the same constant as the facts API
--------------------------------------
`facts/api.ANNUAL_MIN_DAYS/MAX_DAYS` (350/380) filters which durations are
fetched at all. It is a narrower window than SEC's frames rule and it answers
"is this row an annual figure", not "which calendar year does it belong to".
Reusing either for the other question is the mistake this module exists to
prevent.
"""
from dataclasses import dataclass
from datetime import date

#: SEC frames: an annual period is 365 days +/- 30. Their number, for their
#: question -- is this a year at all.
ANNUAL_DAYS = 365
ANNUAL_TOLERANCE_DAYS = 30

#: SEC frames: a quarter is 91 days +/- 30. Unused here; recorded so the next
#: reader does not have to go and look it up again.
QUARTER_DAYS = 91
QUARTER_TOLERANCE_DAYS = 30

DAYS_IN_YEAR = 365

#: THIS PROJECT'S decision, not SEC's. How many days of a fiscal year must fall
#: inside a calendar year before the two may be called the same period.
#:
#: 300 of 365 is roughly "within two months of a calendar filer". It admits the
#: January and November year ends that dominate semiconductors -- NVIDIA at
#: 339, Marvell at 333, Broadcom at 306 -- and refuses the June and September
#: ones, where a third or more of the year is genuinely somewhere else.
#:
#: It is a judgement call and the honest thing is to say so rather than to
#: dress it as a standard. What is NOT a judgement call is the behaviour when
#: it fails: 2.4 says exclusion, by name, never assignment to the nearest year.
DEFAULT_MIN_OVERLAP_DAYS = 300


class PeriodAlignmentError(ValueError):
    """A period cannot be aligned, and guessing would corrupt the panel."""


@dataclass(frozen=True)
class Aligned:
    """One peer's period, and how well it matches the calendar year."""

    start: date
    end: date
    calendar_year: int
    overlap_days: int

    @property
    def overlap_share(self) -> float:
        return self.overlap_days / DAYS_IN_YEAR

    def render(self) -> str:
        return (f"{self.start}..{self.end} -> CY{self.calendar_year} "
                f"({self.overlap_days}/{DAYS_IN_YEAR} days)")


def period_days(start: date, end: date) -> int:
    """Length of a reported period, inclusive of both endpoints."""
    return (end - start).days + 1


def is_annual(start: date, end: date) -> bool:
    """SEC frames' annual rule: 365 days +/- 30. Their number, cited."""
    return abs(period_days(start, end) - ANNUAL_DAYS) <= ANNUAL_TOLERANCE_DAYS


def calendar_overlap_days(start: date, end: date, year: int) -> int:
    """Days of [start, end] that fall inside calendar `year`.

    The measure behind "best align". Zero when they do not meet at all, never
    negative -- a peer that misses the year entirely is not a near miss.
    """
    lo = max(start, date(year, 1, 1))
    hi = min(end, date(year, 12, 31))
    return max(0, (hi - lo).days + 1)


def best_calendar_year(start: date, end: date) -> tuple[int, int]:
    """(year, overlap_days) for the calendar year this period best aligns with.

    A twelve-month period touches at most two calendar years, so both are
    checked and the larger overlap wins. Ties cannot happen for a 365-day
    period: two calendar years splitting it exactly would need 182.5 days each.
    """
    candidates = {start.year, end.year}
    scored = [(calendar_overlap_days(start, end, y), y) for y in candidates]
    overlap, year = max(scored)
    return year, overlap


def calendar_year(start: date, end: date, *,
                  min_overlap_days: int = DEFAULT_MIN_OVERLAP_DAYS) -> int | None:
    """The calendar year this annual period may be reported as, or None.

    None is the load-bearing return value. Returning the nearest year instead
    is precisely the mis-assignment 2.4 calls never acceptable: it produces a
    panel that looks complete and compares a June year against a December one.
    """
    if not is_annual(start, end):
        raise PeriodAlignmentError(
            f"{start}..{end} is {period_days(start, end)} days, not an annual "
            f"period by the SEC frames rule ({ANNUAL_DAYS} +/- "
            f"{ANNUAL_TOLERANCE_DAYS}). A calendar year cannot be derived from "
            f"it, and picking one would be a guess")
    year, overlap = best_calendar_year(start, end)
    return year if overlap >= min_overlap_days else None


def align(periods: dict[str, tuple[date, date]], year: int, *,
          min_overlap_days: int = DEFAULT_MIN_OVERLAP_DAYS
          ) -> tuple[dict[str, Aligned], dict[str, str]]:
    """Split peers into those that may share this calendar column and those
    that may not, with a reason for every exclusion.

    Returns (aligned, excluded). Their keys partition the input exactly: a peer
    that vanished from both would be a silent drop, which is the failure this
    whole module is about.
    """
    aligned: dict[str, Aligned] = {}
    excluded: dict[str, str] = {}

    for name, (start, end) in periods.items():
        if not is_annual(start, end):
            excluded[name] = (
                f"{start}..{end} is {period_days(start, end)} days, not an "
                f"annual period ({ANNUAL_DAYS} +/- {ANNUAL_TOLERANCE_DAYS})")
            continue
        overlap = calendar_overlap_days(start, end, year)
        if overlap >= min_overlap_days:
            aligned[name] = Aligned(start=start, end=end, calendar_year=year,
                                    overlap_days=overlap)
        else:
            excluded[name] = (
                f"{start}..{end} overlaps CY{year} by {overlap} days, under "
                f"the {min_overlap_days}-day floor; excluded rather than "
                f"assigned to the nearest year (framework 2.4)")
    return aligned, excluded


def render_alignment(aligned: dict[str, Aligned], excluded: dict[str, str],
                     year: int) -> str:
    """The exclusions print WITH the panel, never in a log nobody reads."""
    lines = [f"Calendar alignment CY{year} "
             f"(floor {DEFAULT_MIN_OVERLAP_DAYS}/{DAYS_IN_YEAR} days)"]
    for name, a in sorted(aligned.items(), key=lambda kv: -kv[1].overlap_days):
        lines.append(f"  {name:<8} {a.overlap_days:>3}/{DAYS_IN_YEAR}  {a.start}..{a.end}")
    for name, why in sorted(excluded.items()):
        lines.append(f"  {name:<8} EXCLUDED  {why}")
    return "\n".join(lines)
