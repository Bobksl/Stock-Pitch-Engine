"""P2.13 — price target mechanics and the return decomposition (framework 4.9).

    Implied EV     = Target multiple x Forward metric
    Implied Equity = Implied EV + Cash - Debt      (pro-forma, post offering)
    Implied Price  = Implied Equity / Fully diluted shares
    Upside         = Implied Price / Current Price - 1

The decomposition is the part that earns its place
--------------------------------------------------
A target of 2,359 is an assertion. "Of 30% upside, 18 points is estimate
revision and 12 is multiple" is auditable, maps one-to-one onto the Section 3
archetypes -- a growth story earns through the second term, a re-rating story
through the first -- and tells you which catalyst you are actually waiting on.

The three terms are computed by SEQUENTIAL attribution, in the order framework
4.9 lists them, and the order is a real choice rather than a formality.
Multiple change and metric change interact: the cross term (delta-m x delta-e)
has to land somewhere, and moving the multiple first puts it in the metric
terms. Splitting it out as a fourth "interaction" line would be more neutral
and less useful -- three terms that sum exactly to the price change is what a
reader can act on, and the alternative, three terms that nearly sum, is the
worst of both. `residual` is therefore zero by construction and is asserted.

The roll-forward is a term, not a footnote
------------------------------------------
Moving from this year's forward estimate to next year's is a source of return
in its own right, and it is invisible if the metric is treated as one number.
Framework 4.9 requires the multiple to apply to the forward metric relevant at
the valuation date under an explicit convention; applying it to trailing
actuals while the market has moved on to next year is a systematic overstatement
that never announces itself. So the metric change is split: a revision to the
SAME period's estimate, and a roll-forward to the NEXT period's.

Where the target multiple came from
-----------------------------------
A target reverse-engineered from a desired upside is a Class A failure (4.13),
and it is undetectable from the arithmetic -- every step is correct. So the
multiple carries a declared source from a closed vocabulary, the same shape as
external provenance: a peer anchor, a regression fit, or the company's own
history. `undeclared` is legal to construct and fails the gate, because
refusing to build it would just move the fabrication one step earlier.
"""
from dataclasses import dataclass
from decimal import Decimal

from src.valuation.money import D, divide

#: Where a target multiple came from (framework 4.9, 4.13).
SOURCE_PEER_ANCHOR = "peer_anchor"
SOURCE_REGRESSION = "regression_fit"
SOURCE_OWN_HISTORY = "own_trading_history"
SOURCE_UNDECLARED = "undeclared"

MULTIPLE_SOURCES = (SOURCE_PEER_ANCHOR, SOURCE_REGRESSION, SOURCE_OWN_HISTORY,
                    SOURCE_UNDECLARED)


class TargetError(ValueError):
    """The price target cannot be computed as specified."""


@dataclass(frozen=True)
class ShareCount:
    """Fully diluted, with the path shown (framework 4.9).

    The quiet way retail targets end up 15% too high: divide by basic shares,
    ignore the options and RSUs that will be exercised into the very upside
    being forecast, and treat share-based compensation as though it were not a
    cost. Every component is kept so the dilution can be shown rather than
    asserted.
    """

    basic: Decimal
    options: Decimal = Decimal(0)
    restricted_units: Decimal = Decimal(0)
    #: Shares issued in an offering that has priced but not yet settled.
    offering: Decimal = Decimal(0)

    @property
    def fully_diluted(self) -> Decimal:
        return (self.basic + self.options + self.restricted_units
                + self.offering)

    @property
    def dilution(self) -> Decimal:
        """Fully diluted over basic, minus one. What the path costs."""
        if self.basic <= 0:
            raise TargetError("basic share count must be positive")
        return divide(self.fully_diluted, self.basic) - Decimal(1)

    def render(self) -> str:
        from src.valuation.money import as_percent
        return (f"{self.fully_diluted} fully diluted "
                f"= {self.basic} basic + {self.options} options "
                f"+ {self.restricted_units} RSUs + {self.offering} offering "
                f"({as_percent(self.dilution)}% dilution)")


def implied_price(multiple: Decimal, metric: Decimal, cash: Decimal,
                  debt: Decimal, shares: Decimal) -> Decimal:
    """(multiple x metric + cash - debt) / shares. Framework 4.9, in one step."""
    if shares <= 0:
        raise TargetError("share count must be positive")
    return divide(multiple * metric + cash - debt, shares)


@dataclass(frozen=True)
class ReturnDecomposition:
    """Where the return comes from, in the currency and in points of upside."""

    base_price: Decimal
    re_rating: Decimal
    estimate_revision: Decimal
    time_roll_forward: Decimal
    target_price: Decimal

    @property
    def total(self) -> Decimal:
        return self.re_rating + self.estimate_revision + self.time_roll_forward

    @property
    def residual(self) -> Decimal:
        """Zero by construction. A non-zero value is a bug, not a rounding."""
        return self.target_price - self.base_price - self.total

    def points(self, component: Decimal) -> Decimal:
        """One component as percentage points of the starting price."""
        if self.base_price <= 0:
            raise TargetError("base price must be positive to express points")
        return divide(component, self.base_price) * 100

    @property
    def upside_points(self) -> Decimal:
        return self.points(self.total)

    def render(self, currency: str = "") -> str:
        rows = (("re-rating", self.re_rating),
                ("estimate revision", self.estimate_revision),
                ("time roll-forward", self.time_roll_forward))
        lines = [f"Return decomposition — of {self.upside_points:.1f}% upside "
                 f"(framework 4.9)"]
        for name, value in rows:
            lines.append(f"  {name:<20} {currency} {value:>10.2f}   "
                         f"{self.points(value):+6.1f} points")
        lines.append(f"  {'total':<20} {currency} {self.total:>10.2f}   "
                     f"{self.upside_points:+6.1f} points")
        return "\n".join(lines)


@dataclass(frozen=True)
class PriceTarget:
    """A target, its provenance, and how the return breaks down."""

    multiple: Decimal
    multiple_source: str
    forward_metric: Decimal
    cash: Decimal
    debt: Decimal
    shares: ShareCount
    current_price: Decimal
    #: The starting point of the decomposition: the multiple and the same
    #: period's metric as they stood at the valuation date.
    prior_multiple: Decimal | None = None
    prior_metric: Decimal | None = None
    #: The same period's metric after revision, before rolling forward.
    revised_metric: Decimal | None = None
    metric_label: str = ""

    @property
    def implied_enterprise_value(self) -> Decimal:
        return self.multiple * self.forward_metric

    @property
    def implied_equity_value(self) -> Decimal:
        return self.implied_enterprise_value + self.cash - self.debt

    @property
    def price(self) -> Decimal:
        return implied_price(self.multiple, self.forward_metric, self.cash,
                             self.debt, self.shares.fully_diluted)

    @property
    def upside(self) -> Decimal:
        if self.current_price <= 0:
            raise TargetError("current price must be positive")
        return divide(self.price, self.current_price) - Decimal(1)

    def _price_at(self, multiple: Decimal, metric: Decimal) -> Decimal:
        return implied_price(multiple, metric, self.cash, self.debt,
                             self.shares.fully_diluted)

    def decomposition(self) -> ReturnDecomposition:
        """The three terms, summing exactly to the price change (4.9).

        Sequential attribution in the order 4.9 lists: re-rate first at the
        old metric, then revise the same period, then roll forward. The order
        determines where the multiple-by-metric cross term lands, and moving
        the multiple first puts it in the metric terms.
        """
        if self.prior_multiple is None or self.prior_metric is None:
            raise TargetError(
                "a return decomposition needs the multiple and metric as they "
                "stood at the valuation date. Without them the target is a "
                "number rather than an argument about where return comes from "
                "(framework 4.9).")

        revised = self.revised_metric
        if revised is None:
            # No separate revision declared: the whole metric change is a
            # roll-forward. Stated, not assumed away.
            revised = self.prior_metric

        base = self._price_at(self.prior_multiple, self.prior_metric)
        after_rerating = self._price_at(self.multiple, self.prior_metric)
        after_revision = self._price_at(self.multiple, revised)
        target = self._price_at(self.multiple, self.forward_metric)

        return ReturnDecomposition(
            base_price=base,
            re_rating=after_rerating - base,
            estimate_revision=after_revision - after_rerating,
            time_roll_forward=target - after_revision,
            target_price=target)

    def render(self, currency: str = "") -> str:
        from src.valuation.money import as_percent, quantize_price
        lines = [
            f"Price target {currency} {quantize_price(self.price)} "
            f"({as_percent(self.upside):+}% upside)",
            f"  {self.multiple}x {self.metric_label or 'forward metric'} "
            f"[{self.multiple_source}]",
            f"  {self.shares.render()}",
        ]
        if self.prior_multiple is not None and self.prior_metric is not None:
            lines.append(self.decomposition().render(currency))
        return "\n".join(lines)
