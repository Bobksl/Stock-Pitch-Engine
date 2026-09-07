"""P3.1 — framework 1.4h: the type field, derived from profit-weighted reality.

1.4h asks for the dominant segment by revenue **and** by profit, and says
disagreement between the two is itself flagged and discussed. It is the join
key C1 hangs off: it determines which industry section 2 analyses and which
comp set section 4 uses, with GICS as the default and this field as the
override.

Why there are three verdicts and not two
----------------------------------------
The spec names one failure -- the two dominances disagree -- and Broadcom
FY2025 shows it is not the only one. Revenue splits 57.69 / 42.31 to
Semiconductor Solutions, and profit splits **50.56 / 49.44** the same way. The
two dominances agree, so a binary argmax test passes it silently. That
agreement is worth 467m out of 42bn, and it sits on segment margins of 57.60%
against 76.82%.

A field that answers "semiconductor company" there hands section 2 the
semiconductor comp set and section 4 the semiconductor multiple, while half
the profit is enterprise software earning a software margin. The failure mode
1.4h exists to prevent -- GICS unchallenged by profit-weighted reality --
arrives through a near-tie rather than through a flip, and the binary test
cannot see it.

So the near-tie is its own state. `contested` when the top two profit shares
sit within `CONTEST_THRESHOLD`, and a contested or disagreed field sets
`requires_both_types`, which is what C1 checks the comp set against.

The threshold is 10 percentage points, and it is a judgement call rather than
a derived quantity -- there is no principled boundary between a segment that
carries a company and one that does not. It is stated once, here, so that
changing it is a reviewable edit rather than a scatter of inline comparisons.
Broadcom FY2025 lands at 1.11pp and AMD FY2025 at 9.71pp; both are contested,
and both would have passed a binary test.

Derived, never asserted
-----------------------
`dominant_by_revenue` and the rest are properties over `shares`, and `shares`
is built only by `from_panel` out of `Fact` objects. There is no constructor
taking "the dominant segment is X": fabricating one means fabricating the
segment figures it is computed from, which the QC gate then fails to resolve.
The LLM proposes the *narrative* around this field (1.4a) and never the field.

Reconciling items
-----------------
Filers tag things on the segment axis that are not segments. AVGO tags
unallocated expenses there with zero revenue and -6,069m of operating profit
in FY2022 and FY2021. Counted as a segment it corrupts the profit denominator
and can win the argmax outright; dropped silently it is a figure that left the
panel with nobody told. It is excluded structurally -- a member with no
revenue is not a business segment -- and named in `excluded`, which the
section 1 exhibit prints.
"""
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from src.facts.api import Fact, SegmentPanel, pretty_member
from src.valuation.money import divide

#: The two dominances name the same segment, and it leads profit clearly.
AGREED = "agreed"
#: The two dominances name the same segment, but the profit lead is inside
#: CONTEST_THRESHOLD -- no segment carries the company.
CONTESTED = "contested"
#: The two dominances name different segments (1.4h's stated case).
DISAGREED = "disagreed"

VERDICTS = (AGREED, CONTESTED, DISAGREED)

#: Profit-share gap between the top two segments below which the type field is
#: contested. A judgement call; see the module docstring.
CONTEST_THRESHOLD = Decimal("0.10")

#: Why a member tagged on the segment axis was left out of the shares.
RECONCILING_ITEM = "reconciling_item"


class TypeFieldError(ValueError):
    """The type field cannot be derived from this panel, and saying so is the
    only honest answer. A wrong-but-plausible type classification is worse
    than a hard failure -- it silently selects the wrong comp set."""


@dataclass(frozen=True)
class SegmentShare:
    """One reportable segment's weight in the period, revenue and profit both."""

    member: str                 # the qname as the filer tagged it
    label: str                  # display form
    revenue: Decimal
    profit: Decimal
    revenue_share: Decimal
    profit_share: Decimal
    revenue_fact: Fact
    profit_fact: Fact

    @property
    def margin(self) -> Decimal:
        """Segment operating margin. The reason a near-tie in profit matters:
        two segments at the same profit share and different margins are not
        the same business."""
        return divide(self.profit, self.revenue)


@dataclass(frozen=True)
class ExcludedMember:
    """A member on the segment axis that is not a reportable segment."""

    member: str
    label: str
    reason: str

    def render(self) -> str:
        return f"{self.label} - excluded: {self.reason}"


@dataclass(frozen=True)
class TypeField:
    """Framework 1.4h. Every field below is computed; none is asserted."""

    period_end: date
    #: Business segments, ordered by profit share, largest first.
    shares: tuple[SegmentShare, ...]
    #: Members left out, each with its reason. Never silently dropped.
    excluded: tuple[ExcludedMember, ...]
    #: The GICS classification this field either confirms or overrides.
    gics: str | None = None

    # -- the two dominances -------------------------------------------------
    @property
    def dominant_by_revenue(self) -> str:
        return max(self.shares, key=lambda s: s.revenue_share).label

    @property
    def dominant_by_profit(self) -> str:
        return self.shares[0].label

    @property
    def revenue_share(self) -> Decimal:
        """Revenue share of the revenue-dominant segment."""
        return max(s.revenue_share for s in self.shares)

    @property
    def profit_share(self) -> Decimal:
        """Profit share of the profit-dominant segment."""
        return self.shares[0].profit_share

    @property
    def profit_gap(self) -> Decimal:
        """Profit share of the leader less that of the runner-up.

        Computed from the full-precision shares, not from rounded ones: at the
        threshold the difference decides the verdict. A single-segment company
        has no runner-up and the whole of the profit, so the gap is 1.
        """
        if len(self.shares) == 1:
            return Decimal(1)
        return self.shares[0].profit_share - self.shares[1].profit_share

    # -- the verdict --------------------------------------------------------
    @property
    def verdict(self) -> str:
        if self.dominant_by_revenue != self.dominant_by_profit:
            return DISAGREED
        return CONTESTED if self.profit_gap < CONTEST_THRESHOLD else AGREED

    @property
    def requires_both_types(self) -> bool:
        """C1: may section 2 analyse one industry and section 4 use one comp set?

        Only when a single segment demonstrably carries the company. Contested
        and disagreed both mean the comp set has to justify covering the
        second segment rather than inheriting the GICS single type.
        """
        return self.verdict != AGREED

    @property
    def overrides_gics(self) -> bool:
        """1.4h: GICS is the default, overridden by profit-weighted reality."""
        return self.gics is not None and self.requires_both_types

    def render(self) -> str:
        lines = [f"Type field ({self.period_end}) - {self.verdict.upper()}",
                 f"  dominant by revenue  {self.dominant_by_revenue} "
                 f"({self.revenue_share:.2%})",
                 f"  dominant by profit   {self.dominant_by_profit} "
                 f"({self.profit_share:.2%})",
                 f"  profit gap to runner-up {self.profit_gap:.2%} "
                 f"(contested below {CONTEST_THRESHOLD:.0%})"]
        for s in self.shares:
            lines.append(f"    {s.label:<28} rev {s.revenue_share:>7.2%} "
                         f"profit {s.profit_share:>7.2%}  margin {s.margin:>7.2%}")
        lines.extend(f"    {e.render()}" for e in self.excluded)
        if self.gics:
            verb = "overridden by" if self.overrides_gics else "confirmed by"
            lines.append(f"  GICS {self.gics!r} {verb} the profit split")
        return "\n".join(lines)

    # -- the only constructor ----------------------------------------------
    @classmethod
    def from_panel(cls, panel: SegmentPanel, period_end: date, *,
                   gics: str | None = None) -> "TypeField":
        """Derive the type field from one period of a segment panel."""
        rows = [(member, cell) for (pe, member), cell in panel.cells.items()
                if pe == period_end]
        if not rows:
            raise TypeFieldError(
                f"no reportable segment breakdown for {period_end}: the type "
                f"field is 1.4h's join key and cannot be guessed at")

        segments, excluded = [], []
        for member, cell in rows:
            revenue = cell.value("revenue")
            if revenue is None or revenue == 0:
                # Not a business segment: an unallocated-expenses or
                # intersegment-elimination row the filer tagged on this axis.
                excluded.append(ExcludedMember(
                    member=member, label=pretty_member(member),
                    reason=RECONCILING_ITEM))
                continue
            profit = cell.value("operating_income")
            if profit is None:
                raise TypeFieldError(
                    f"{pretty_member(member)} reports segment revenue with no "
                    f"segment operating profit for {period_end}. Framework 1.3 "
                    f"makes segment profit required, not optional")
            segments.append((member, revenue, profit, cell))

        if not segments:
            raise TypeFieldError(
                f"no reportable segment breakdown for {period_end}: every "
                f"member on the segment axis is a reconciling item")

        total_revenue = sum(r for _, r, _, _ in segments)
        total_profit = sum(p for _, _, p, _ in segments)
        if total_profit <= 0:
            raise TypeFieldError(
                f"aggregate segment profit for {period_end} is {total_profit}: "
                f"a profit-weighted type classification is undefined when the "
                f"segments do not sum to a profit")

        shares = tuple(sorted(
            (SegmentShare(
                member=member, label=pretty_member(member),
                revenue=revenue, profit=profit,
                revenue_share=divide(revenue, total_revenue),
                profit_share=divide(profit, total_profit),
                revenue_fact=cell.facts["revenue"],
                profit_fact=cell.facts["operating_income"])
             for member, revenue, profit, cell in segments),
            key=lambda s: s.profit_share, reverse=True))

        return cls(period_end=period_end, shares=shares,
                   excluded=tuple(excluded), gics=gics)
