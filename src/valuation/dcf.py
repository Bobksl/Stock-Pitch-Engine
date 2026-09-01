"""P2.3 — the discounted cash flow (framework 4.5, 4.6).

The forecast drivers are the Section 3 bridge, not independent assumptions
(4.5). This module computes; it does not invent a driver, and C3 will assert
the equality once Section 3 exists.

Three places a DCF goes wrong, all three enumerated in `Conventions` rather
than hidden in a branch, because the acceptance fixture gets all three wrong
and the engine has to be able to reproduce a defective model faithfully before
it can prove the defect.

**Terminal value.** `TV = UFCF_final x (1+g) / (WACC-g)`, discounted once. The
final *undiscounted* cash flow. Building it from the already-discounted one
and then discounting the result again applies the final period's factor twice,
which on the fixture understates the target by 36%. The arithmetic is
unremarkable, the output looks plausible, and no amount of careful reading
catches it -- the only defence is recomputation.

**The stub period.** A valuation part-way through a year discounts a
*pro-rated slice* of that year's cash flow at the matching partial factor.
Discounting the full year at a two-month factor collects twelve months of cash
for two months of waiting. Either count 2/12 of the cash flow, or wait the
full year for all of it; the fixture does neither.

**Terminal growth is nominal.** A real GDP growth rate applied to nominal cash
flows is a unit mismatch, and this module cannot detect it -- 0.0445 is an
ordinary number to multiply by. That check lives with provenance (P2.7),
where g must resolve to a declared record whose unit says nominal.

The `WACC-g` spread is computed and carried on every result, pass or fail.
Below 4 points the model is a terminal-value assumption wearing a DCF as a
disguise (4.6), and on the fixture it is 3.13 -- but that is a Class B finding
for the QC gate to raise, not an exception for this module to throw.
"""
from dataclasses import dataclass
from decimal import Decimal

from src.valuation.inputs import (
    STUB_FULL_YEAR_AT_STUB_FACTOR,
    STUB_PRORATE_CASH_FLOW,
    TV_FROM_DISCOUNTED_UFCF,
    TV_FROM_UNDISCOUNTED_UFCF,
    Conventions,
    ValuationInputs,
)
from src.valuation.money import D, divide, power
from src.valuation.wacc import CostOfCapital, cost_of_capital


class DcfError(ValueError):
    """The model cannot be computed as specified."""


@dataclass(frozen=True)
class Period:
    """One explicit-forecast year, every line recomputable by hand."""

    period: int
    revenue: Decimal
    ebitda: Decimal
    depreciation: Decimal
    ebit: Decimal
    tax: Decimal                    # negative: a charge
    capex: Decimal                  # negative
    change_in_nwc: Decimal          # negative when working capital absorbs cash
    unlevered_fcf: Decimal
    discount_exponent: Decimal
    discount_factor: Decimal
    cash_flow_discounted: Decimal   # the slice actually discounted (stub policy)
    present_value: Decimal


@dataclass(frozen=True)
class DcfResult:
    """A valuation, and everything needed to audit how it was reached."""

    inputs: ValuationInputs
    conventions: Conventions
    capital: CostOfCapital
    periods: tuple[Period, ...]
    pv_forecast: Decimal
    terminal_value: Decimal
    pv_terminal_value: Decimal
    enterprise_value: Decimal
    equity_value: Decimal
    share_price: Decimal

    @property
    def wacc(self) -> Decimal:
        return self.capital.wacc

    @property
    def terminal_growth(self) -> Decimal:
        return self.inputs.terminal_growth

    @property
    def spread_to_terminal_growth(self) -> Decimal:
        """WACC - g. Diagnostic on every run, threshold 4pp (4.6)."""
        return self.capital.wacc - self.inputs.terminal_growth

    @property
    def terminal_value_share(self) -> Decimal:
        """PV(TV) as a fraction of enterprise value.

        Reported on every run, pass or fail (4.6). A single hard threshold of
        75% blocks; there is deliberately no lower non-blocking tier, because
        an observation that cannot block is a warning by another name.
        """
        return divide(self.pv_terminal_value, self.enterprise_value)

    @property
    def implied_exit_multiple(self) -> Decimal:
        """TV / final-year EBITDA, for the cross-check 4.6 requires."""
        return divide(self.terminal_value, self.periods[-1].ebitda)


def _build_periods(inputs: ValuationInputs, wacc: Decimal,
                   conventions: Conventions) -> tuple[Period, ...]:
    revenue = inputs.base_revenue
    periods: list[Period] = []

    for index, year in enumerate(inputs.forecast):
        revenue = revenue * (Decimal(1) + year.revenue_growth)
        ebitda = revenue * year.ebitda_margin
        ebit = ebitda - year.depreciation
        tax = -ebit * inputs.tax_rate
        # Capex and the working-capital movement are already signed.
        ufcf = ebitda + tax + year.capex + year.change_in_nwc

        exponent = inputs.stub_fraction + index
        factor = divide(Decimal(1), power(Decimal(1) + wacc, exponent))

        if index == 0 and conventions.stub_policy == STUB_PRORATE_CASH_FLOW:
            # Wait a fraction of a year, collect that fraction of the cash.
            discounted_slice = ufcf * inputs.stub_fraction
        elif index == 0 and conventions.stub_policy == STUB_FULL_YEAR_AT_STUB_FACTOR:
            # Defect 7: a full year of cash flow for a partial year of waiting.
            discounted_slice = ufcf
        elif index == 0:
            raise DcfError(f"unknown stub policy {conventions.stub_policy!r}")
        else:
            discounted_slice = ufcf

        periods.append(Period(
            period=year.period, revenue=revenue, ebitda=ebitda,
            depreciation=year.depreciation, ebit=ebit, tax=tax,
            capex=year.capex, change_in_nwc=year.change_in_nwc,
            unlevered_fcf=ufcf, discount_exponent=exponent,
            discount_factor=factor, cash_flow_discounted=discounted_slice,
            present_value=discounted_slice * factor))

    return tuple(periods)


def _terminal_value(periods: tuple[Period, ...], wacc: Decimal,
                    growth: Decimal, basis: str) -> Decimal:
    final = periods[-1]
    if basis == TV_FROM_UNDISCOUNTED_UFCF:
        base = final.unlevered_fcf
    elif basis == TV_FROM_DISCOUNTED_UFCF:
        # Defect 1. The result is then discounted again by the caller, applying
        # the final period's factor twice.
        base = final.present_value
    else:
        raise DcfError(f"unknown terminal value basis {basis!r}")

    spread = wacc - growth
    if spread <= 0:
        raise DcfError(
            f"terminal growth {growth} is not below WACC {wacc}: the perpetuity "
            f"does not converge and no terminal value exists")
    return divide(base * (Decimal(1) + growth), spread)


def discounted_cash_flow(inputs: ValuationInputs,
                         conventions: Conventions = Conventions.SPEC,
                         capital: CostOfCapital | None = None) -> DcfResult:
    """Value the explicit forecast plus a perpetuity, under stated conventions."""
    if not inputs.forecast:
        raise DcfError("a DCF needs at least one explicit forecast period")

    capital = capital or cost_of_capital(inputs, conventions)
    periods = _build_periods(inputs, capital.wacc, conventions)

    pv_forecast = sum((p.present_value for p in periods), D(0))
    terminal_value = _terminal_value(
        periods, capital.wacc, inputs.terminal_growth,
        conventions.terminal_value_base)
    pv_terminal_value = terminal_value * periods[-1].discount_factor

    enterprise_value = pv_forecast + pv_terminal_value
    # total_debt is carried signed, as the workbook's own bridge states it.
    equity_value = (enterprise_value + inputs.total_debt
                    + inputs.cash_and_equivalents)
    if inputs.shares_outstanding <= 0:
        raise DcfError("share count must be positive and fully diluted (4.9)")

    return DcfResult(
        inputs=inputs, conventions=conventions, capital=capital, periods=periods,
        pv_forecast=pv_forecast, terminal_value=terminal_value,
        pv_terminal_value=pv_terminal_value, enterprise_value=enterprise_value,
        equity_value=equity_value,
        share_price=divide(equity_value, inputs.shares_outstanding))
