"""P2.14 — scenarios and sensitivity (framework 4.10).

**Scenarios are thesis pillars succeeding or failing, never arbitrary tweaks.**
A bull case built by adding ten percent to every line is not a scenario, it is
the base case in a louder font: it tests nothing, because nothing in it could
have turned out differently for a reason anyone could name in advance. So a
`Scenario` must cite at least one declared pillar, and one citing none — or
citing a pillar nobody declared — is a Class A failure under 4.13.

**Probabilities are coarse on purpose.** The default is 60/25/15 and every
weight must be a multiple of five points. Nobody knows a thesis is 63% likely,
and writing 63 rather than 60 manufactures a precision the estimate does not
have — which then propagates into an expected value quoted to the cent. The
constraint is enforced rather than suggested, because a rule that survives
only while someone remembers it is not a rule.

**The expected value is what makes ideas comparable.** A probability-weighted
target lets the portfolio layer rank this idea against another whose bull case
is larger but less likely, which no single target price permits.

**Sensitivity is ranked, not scattered.** 4.10 asks for the top three
assumptions named explicitly, so `rank_leverage` shocks each candidate by the
same relative amount and orders them by how far the target moves. That ordering
is frequently the most useful output of the whole valuation: it says which
argument the thesis actually rests on, and it is often not the one the write-up
spends its words on.
"""
from dataclasses import dataclass, replace
from decimal import Decimal
from typing import Mapping

from src.valuation.dcf import DcfResult, discounted_cash_flow
from src.valuation.inputs import Conventions, ValuationInputs
from src.valuation.money import D, divide

#: Framework 4.10: coarse buckets, no false decimals. Every weight is a
#: multiple of five percentage points.
PROBABILITY_STEP = Decimal("0.05")

#: The default weighting 4.10 names.
DEFAULT_WEIGHTS = {"bull": Decimal("0.25"), "base": Decimal("0.60"),
                   "bear": Decimal("0.15")}

#: Driver fields a scenario may override across the whole forecast.
FLAT_DRIVERS = ("revenue_growth", "ebitda_margin")


class ScenarioError(ValueError):
    """A scenario set that cannot be weighted or traced."""


@dataclass(frozen=True)
class Pillar:
    """One load-bearing claim of the thesis (framework 3.3)."""

    name: str
    claim: str


@dataclass(frozen=True)
class Scenario:
    """A case, the pillars it turns on, and what it changes."""

    name: str
    probability: Decimal
    pillars: tuple[str, ...]
    #: Scalar overrides applied to ValuationInputs, e.g. terminal_growth.
    overrides: Mapping[str, Decimal] = None
    #: Flat overrides applied to every forecast year, e.g. ebitda_margin.
    driver_overrides: Mapping[str, Decimal] = None
    narrative: str = ""

    def apply(self, inputs: ValuationInputs) -> ValuationInputs:
        """This scenario's inputs, from the base case."""
        updated = inputs
        for field, value in (self.overrides or {}).items():
            if not hasattr(updated, field):
                raise ScenarioError(
                    f"{self.name}: no input field {field!r} to override")
            updated = replace(updated, **{field: value})

        drivers = self.driver_overrides or {}
        for field in drivers:
            if field not in FLAT_DRIVERS:
                raise ScenarioError(
                    f"{self.name}: {field!r} is not a flat driver; legal ones "
                    f"are {FLAT_DRIVERS}")
        if drivers:
            updated = replace(updated, forecast=tuple(
                replace(year, **drivers) for year in updated.forecast))
        return updated

    def value(self, inputs: ValuationInputs,
              conventions: Conventions = Conventions.SPEC) -> DcfResult:
        return discounted_cash_flow(self.apply(inputs), conventions)


@dataclass(frozen=True)
class WeightedOutcome:
    scenario: Scenario
    result: DcfResult

    @property
    def contribution(self) -> Decimal:
        return self.scenario.probability * self.result.share_price


@dataclass(frozen=True)
class ScenarioSet:
    """Bull, base and bear, weighted and traceable."""

    pillars: tuple[Pillar, ...]
    outcomes: tuple[WeightedOutcome, ...]

    @property
    def expected_value(self) -> Decimal:
        """Probability-weighted target, for cross-idea ranking (4.10)."""
        return sum((o.contribution for o in self.outcomes), D(0))

    def by_name(self, name: str) -> WeightedOutcome:
        for outcome in self.outcomes:
            if outcome.scenario.name == name:
                return outcome
        raise ScenarioError(f"no scenario named {name!r}")

    def render(self, currency: str = "") -> str:
        from src.valuation.money import as_percent, quantize_price
        lines = ["Scenarios — weighted to thesis pillars (framework 4.10)"]
        for outcome in self.outcomes:
            lines.append(
                f"  {outcome.scenario.name:<6} "
                f"{as_percent(outcome.scenario.probability):>3}%  "
                f"{currency} {quantize_price(outcome.result.share_price):>10}  "
                f"pillars: {', '.join(outcome.scenario.pillars)}")
        lines.append(f"  {'EV':<6}      {currency} "
                     f"{quantize_price(self.expected_value):>10}")
        return "\n".join(lines)


def validate_scenarios(scenarios: tuple[Scenario, ...],
                       pillars: tuple[Pillar, ...]) -> None:
    """Weights coarse and summing to one; every case traceable to a pillar."""
    if not scenarios:
        raise ScenarioError("no scenarios")

    total = sum((s.probability for s in scenarios), D(0))
    if total != 1:
        raise ScenarioError(
            f"probabilities sum to {total}, not 1. A weighted expected value "
            f"over weights that do not sum to one is not an expected value.")

    for scenario in scenarios:
        remainder = scenario.probability % PROBABILITY_STEP
        if remainder != 0:
            raise ScenarioError(
                f"{scenario.name}: probability {scenario.probability} is not a "
                f"multiple of {PROBABILITY_STEP}. Framework 4.10 requires "
                f"coarse buckets -- nobody knows a thesis is 63% likely, and "
                f"writing 63 manufactures precision the estimate lacks.")

    declared = {p.name for p in pillars}
    for scenario in scenarios:
        if not scenario.pillars:
            raise ScenarioError(
                f"{scenario.name}: cites no thesis pillar. A case built by "
                f"tweaking inputs tests nothing, because nothing in it could "
                f"have turned out differently for a nameable reason (4.10).")
        unknown = set(scenario.pillars) - declared
        if unknown:
            raise ScenarioError(
                f"{scenario.name}: cites undeclared pillar(s) "
                f"{sorted(unknown)}; declared are {sorted(declared)}")


def build_scenarios(inputs: ValuationInputs, scenarios: tuple[Scenario, ...],
                    pillars: tuple[Pillar, ...],
                    conventions: Conventions = Conventions.SPEC) -> ScenarioSet:
    """Value every case and weight them (framework 4.10)."""
    validate_scenarios(scenarios, pillars)
    return ScenarioSet(
        pillars=pillars,
        outcomes=tuple(WeightedOutcome(s, s.value(inputs, conventions))
                       for s in scenarios))


# --------------------------------------------------------------------------
# Sensitivity (framework 4.10)
# --------------------------------------------------------------------------

#: Candidate assumptions to rank, as (label, kind, field). `kind` says whether
#: the field sits on the inputs or on every forecast year.
LEVERAGE_CANDIDATES = (
    ("Terminal growth", "scalar", "terminal_growth"),
    ("Beta", "scalar", "beta"),
    ("Equity risk premium", "scalar", "equity_risk_premium"),
    ("Cost of debt", "scalar", "cost_of_debt"),
    ("EBITDA margin", "driver", "ebitda_margin"),
    ("Revenue growth", "driver", "revenue_growth"),
)

#: The relative shock applied to every candidate when ranking. The same
#: proportional nudge for each, so the ordering compares like with like rather
#: than rewarding whichever assumption happens to be measured in bigger units.
LEVERAGE_SHOCK = Decimal("0.10")


@dataclass(frozen=True)
class Leverage:
    """How far the target moves when one assumption is nudged."""

    label: str
    kind: str
    field: str
    base_price: Decimal
    shocked_price: Decimal

    @property
    def move(self) -> Decimal:
        return self.shocked_price - self.base_price

    @property
    def relative_move(self) -> Decimal:
        return divide(abs(self.move), self.base_price)


def _shift(inputs: ValuationInputs, kind: str, field: str,
           factor: Decimal) -> ValuationInputs:
    if kind == "scalar":
        return replace(inputs, **{field: getattr(inputs, field) * factor})
    return replace(inputs, forecast=tuple(
        replace(year, **{field: getattr(year, field) * factor})
        for year in inputs.forecast))


def rank_leverage(inputs: ValuationInputs,
                  conventions: Conventions = Conventions.SPEC,
                  candidates=LEVERAGE_CANDIDATES,
                  shock: Decimal = LEVERAGE_SHOCK) -> tuple[Leverage, ...]:
    """Every candidate assumption, ordered by how much the target moves.

    Framework 4.10 wants the top three named explicitly. The ordering is
    often the most useful single output of a valuation: it says what the
    thesis actually rests on, which is regularly not what the write-up spends
    its words on.
    """
    base = discounted_cash_flow(inputs, conventions).share_price
    ranked = []
    for label, kind, field in candidates:
        try:
            shocked = discounted_cash_flow(
                _shift(inputs, kind, field, Decimal(1) + shock),
                conventions).share_price
        except Exception:                          # noqa: BLE001 - see below
            # A shock that makes the model uncomputable (g through WACC, say)
            # is itself a statement about leverage, but not one this ranking
            # can order, so the candidate is skipped rather than ranked at an
            # arbitrary value.
            continue
        ranked.append(Leverage(label, kind, field, base, shocked))
    return tuple(sorted(ranked, key=lambda l: l.relative_move, reverse=True))


def top_assumptions(inputs: ValuationInputs,
                    conventions: Conventions = Conventions.SPEC,
                    count: int = 3) -> tuple[Leverage, ...]:
    """The `count` highest-leverage assumptions, named explicitly (4.10)."""
    return rank_leverage(inputs, conventions)[:count]


@dataclass(frozen=True)
class TwoWayTable:
    """A grid of target prices over two assumptions (framework 4.10)."""

    row_label: str
    row_field: str
    row_values: tuple[Decimal, ...]
    column_label: str
    column_field: str
    column_values: tuple[Decimal, ...]
    prices: tuple[tuple[Decimal, ...], ...]
    #: Whether each axis is a rate (rendered as a percentage) or a plain
    #: number. Declared rather than inferred from magnitude: a beta of 0.9 and
    #: a growth rate of 0.9 are indistinguishable to a heuristic and are not
    #: remotely the same quantity.
    row_is_rate: bool = True
    column_is_rate: bool = True

    def at(self, row: int, column: int) -> Decimal:
        return self.prices[row][column]

    @staticmethod
    def _axis(value: Decimal, is_rate: bool) -> str:
        from src.valuation.money import as_percent
        return f"{as_percent(value)}%" if is_rate else f"{value}"

    def render(self, currency: str = "") -> str:
        from src.valuation.money import quantize_price
        header = " " * 14 + "".join(
            f"{self._axis(v, self.column_is_rate):>11}"
            for v in self.column_values)
        lines = [f"Sensitivity — {self.row_label} against {self.column_label} "
                 f"({currency})", header]
        for index, row_value in enumerate(self.row_values):
            cells = "".join(f"{quantize_price(p):>11}" for p in self.prices[index])
            lines.append(
                f"{self._axis(row_value, self.row_is_rate):>13} {cells}")
        return "\n".join(lines)


def two_way_table(inputs: ValuationInputs, row_field: str,
                  row_values: tuple[Decimal, ...], column_field: str,
                  column_values: tuple[Decimal, ...],
                  conventions: Conventions = Conventions.SPEC,
                  row_label: str = "", column_label: str = "",
                  row_is_rate: bool = True,
                  column_is_rate: bool = True) -> TwoWayTable:
    """Target price across a grid of two scalar assumptions."""
    if row_field == column_field:
        raise ScenarioError(
            "a two-way table needs two different assumptions; both axes are "
            f"{row_field!r}")

    grid = []
    for row_value in row_values:
        row = []
        for column_value in column_values:
            shifted = replace(inputs, **{row_field: row_value,
                                         column_field: column_value})
            row.append(discounted_cash_flow(shifted, conventions).share_price)
        grid.append(tuple(row))

    return TwoWayTable(
        row_label=row_label or row_field, row_field=row_field,
        row_values=tuple(row_values),
        column_label=column_label or column_field, column_field=column_field,
        column_values=tuple(column_values), prices=tuple(grid),
        row_is_rate=row_is_rate, column_is_rate=column_is_rate)
