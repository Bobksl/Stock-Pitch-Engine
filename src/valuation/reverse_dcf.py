"""P2.11 — the reverse DCF: what does today's price already assume? (framework 4.7)

Required, not optional. A forward DCF says "here is my number"; a reverse DCF
says "here is what you must already believe to pay today's price", and the
second is far harder to wave away. For a re-rating thesis or a "the market
misunderstands this" thesis it is usually the more persuasive of the two, and
once the forward model exists it is nearly free.

The output is an argument, not a valuation. "The price implies 14% revenue
growth for six years and a 4.5% perpetuity" invites exactly one question --
is that plausible? -- and that question is answerable from Section 2's
industry work in a way that "my target is 2,359" is not.

Solving
-------
Bisection, in `Decimal`, deliberately.

Newton's method would converge faster and is the obvious choice, but it needs
a derivative of a function that is only piecewise smooth here -- the terminal
value has a pole at `g = WACC`, and a Newton step that lands past it does not
produce a wrong answer, it produces a negative enterprise value and a
plausible-looking number on the far side of a discontinuity. Bisection cannot
step over the pole: it only ever narrows a bracket it has already proved
contains a sign change. On a problem where the failure mode is "silently
returns a confident wrong answer", that is worth more than the iteration count.

No scipy, and no float. The whole engine is Decimal, and a solver that dropped
to binary64 for the search would make the answer's last digits meaningless in
exactly the module whose output is a claim about what the market believes.
"""
from dataclasses import dataclass, replace
from decimal import Decimal
from typing import Callable

from src.valuation.dcf import DcfResult, discounted_cash_flow
from src.valuation.inputs import Conventions, ValuationInputs
from src.valuation.money import D, divide

#: Absolute price tolerance for the search, in the model's own currency unit.
#: A hundredth of a currency unit: tighter than any price is quoted, and far
#: tighter than the assumption being solved for is knowable.
PRICE_TOLERANCE = Decimal("0.0001")

#: Bisection halves the bracket each step, so 200 iterations narrows any
#: plausible starting bracket far below the tolerance. Reaching this limit
#: means the function is not behaving as assumed, which is a bug to report,
#: not a result to round.
MAX_ITERATIONS = 200


class ReverseDcfError(ValueError):
    """The implied assumption cannot be solved for."""


@dataclass(frozen=True)
class ImpliedAssumption:
    """What the market must believe, and how confidently it was recovered."""

    name: str
    value: Decimal
    price: Decimal                  # the price this assumption reproduces
    target_price: Decimal           # the price it was solved against
    iterations: int
    bracket: tuple[Decimal, Decimal]

    @property
    def residual(self) -> Decimal:
        return abs(self.price - self.target_price)

    def render(self, currency: str = "") -> str:
        from src.valuation.money import as_percent, quantize_price
        return (f"{self.name}: {as_percent(self.value)}% implied by "
                f"{currency} {quantize_price(self.target_price)} "
                f"(solved to {self.residual:.2e} in {self.iterations} steps)")


def _bisect(price_of: Callable[[Decimal], Decimal], target: Decimal,
            low: Decimal, high: Decimal, name: str) -> ImpliedAssumption:
    """Narrow a bracket that provably contains the answer."""
    def error(x: Decimal) -> Decimal:
        return price_of(x) - target

    try:
        low_error, high_error = error(low), error(high)
    except Exception as exc:                      # noqa: BLE001 - reported below
        raise ReverseDcfError(
            f"{name}: the model does not evaluate across the bracket "
            f"[{low}, {high}]: {exc}") from None

    if low_error == 0:
        return ImpliedAssumption(name, low, price_of(low), target, 0, (low, high))
    if high_error == 0:
        return ImpliedAssumption(name, high, price_of(high), target, 0, (low, high))
    if (low_error > 0) == (high_error > 0):
        raise ReverseDcfError(
            f"{name}: no solution in [{low}, {high}] -- the model prices that "
            f"range at [{price_of(low)}, {price_of(high)}] and the target "
            f"{target} lies outside it. Today's price implies an assumption "
            f"beyond any value worth solving for, which is itself the finding.")

    for iteration in range(1, MAX_ITERATIONS + 1):
        middle = divide(low + high, D(2))
        middle_price = price_of(middle)
        if abs(middle_price - target) <= PRICE_TOLERANCE:
            return ImpliedAssumption(name, middle, middle_price, target,
                                     iteration, (low, high))
        if (middle_price - target > 0) == (low_error > 0):
            low, low_error = middle, middle_price - target
        else:
            high = middle

    raise ReverseDcfError(
        f"{name}: did not converge in {MAX_ITERATIONS} steps; the bracket is "
        f"[{low}, {high}] and the function may not be monotonic there")


def implied_terminal_growth(inputs: ValuationInputs, market_price: Decimal,
                            conventions: Conventions = Conventions.SPEC,
                            bracket: tuple[Decimal, Decimal] | None = None
                            ) -> ImpliedAssumption:
    """The perpetuity growth today's price implies, holding the forecast fixed.

    The upper bound stops short of WACC on purpose. At `g = WACC` the
    perpetuity does not converge, and approaching it the implied price rises
    without limit -- so any price is 'achievable' with a growth rate close
    enough to the discount rate, which is not a finding about the company.
    """
    capital_rate = discounted_cash_flow(inputs, conventions).wacc
    if bracket is None:
        # Stop a full point below WACC: nearer than that the answer is a
        # statement about the asymptote, not about the business.
        bracket = (Decimal("-0.10"), capital_rate - Decimal("0.01"))

    def price_of(growth: Decimal) -> Decimal:
        return discounted_cash_flow(
            replace(inputs, terminal_growth=growth), conventions).share_price

    return _bisect(price_of, market_price, bracket[0], bracket[1],
                   "implied terminal growth")


def implied_revenue_growth(inputs: ValuationInputs, market_price: Decimal,
                           conventions: Conventions = Conventions.SPEC,
                           bracket: tuple[Decimal, Decimal] | None = None
                           ) -> ImpliedAssumption:
    """The flat revenue growth rate today's price implies across the forecast.

    A single rate applied to every explicit year, which is a simplification and
    an honest one: the question this answers is "what compound growth is
    priced in", and a shaped path would recover a curve nobody can falsify
    rather than one number an industry analyst can argue with.
    """
    if bracket is None:
        bracket = (Decimal("-0.50"), Decimal("1.00"))

    def price_of(growth: Decimal) -> Decimal:
        forecast = tuple(replace(year, revenue_growth=growth)
                         for year in inputs.forecast)
        return discounted_cash_flow(
            replace(inputs, forecast=forecast), conventions).share_price

    return _bisect(price_of, market_price, bracket[0], bracket[1],
                   "implied revenue growth")


def implied_ebitda_margin(inputs: ValuationInputs, market_price: Decimal,
                          conventions: Conventions = Conventions.SPEC,
                          bracket: tuple[Decimal, Decimal] | None = None
                          ) -> ImpliedAssumption:
    """The flat EBITDA margin today's price implies across the forecast."""
    if bracket is None:
        bracket = (Decimal("0.01"), Decimal("0.99"))

    def price_of(margin: Decimal) -> Decimal:
        forecast = tuple(replace(year, ebitda_margin=margin)
                         for year in inputs.forecast)
        return discounted_cash_flow(
            replace(inputs, forecast=forecast), conventions).share_price

    return _bisect(price_of, market_price, bracket[0], bracket[1],
                   "implied EBITDA margin")


@dataclass(frozen=True)
class ReverseDcf:
    """Everything today's price implies, one assumption at a time."""

    market_price: Decimal
    forward: DcfResult
    terminal_growth: ImpliedAssumption | None = None
    revenue_growth: ImpliedAssumption | None = None
    ebitda_margin: ImpliedAssumption | None = None
    unsolved: tuple[str, ...] = ()

    @property
    def assumptions(self) -> tuple[ImpliedAssumption, ...]:
        return tuple(a for a in (self.terminal_growth, self.revenue_growth,
                                 self.ebitda_margin) if a is not None)

    def render(self) -> str:
        currency = self.forward.inputs.currency
        from src.valuation.money import quantize_price
        lines = [f"Reverse DCF — what {currency} "
                 f"{quantize_price(self.market_price)} already assumes (4.7)"]
        lines += [f"  {a.render(currency)}" for a in self.assumptions]
        lines += [f"  {name}: no solution in the searched range"
                  for name in self.unsolved]
        return "\n".join(lines)


def reverse_dcf(inputs: ValuationInputs, market_price: Decimal,
                conventions: Conventions = Conventions.SPEC) -> ReverseDcf:
    """Back out what today's price implies, one assumption at a time.

    One at a time, because solving for several together has infinitely many
    answers and would let the analyst choose the flattering combination. Each
    figure here means "holding everything else at the forecast, this is what
    the price requires".

    An assumption that cannot be solved within its range is recorded as
    unsolved rather than dropped: "the price implies growth beyond any rate
    worth searching" is a finding, and silently omitting it would read as
    though the question had not been asked.
    """
    solvers = (("terminal_growth", implied_terminal_growth),
               ("revenue_growth", implied_revenue_growth),
               ("ebitda_margin", implied_ebitda_margin))

    solved: dict[str, ImpliedAssumption] = {}
    unsolved: list[str] = []
    for name, solve in solvers:
        try:
            solved[name] = solve(inputs, market_price, conventions)
        except ReverseDcfError:
            unsolved.append(name)

    return ReverseDcf(market_price=market_price,
                      forward=discounted_cash_flow(inputs, conventions),
                      unsolved=tuple(unsolved), **solved)
