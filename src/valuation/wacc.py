"""P2.3 — cost of capital, built from inputs (framework 4.3).

Never copied. A WACC lifted from a terminal is a Class A failure under 4.13
regardless of whether the number happens to be right, because a figure nobody
can recompute is a figure nobody can check -- and the discount rate is the
single assumption a terminal-value-dominated model is most sensitive to.

Two things here are easy to get wrong and both appear in the acceptance
fixture.

**The equity weight is market capitalisation.** Netting debt out of market cap
produces a quantity with no definition: market cap already *is* the market
value of equity, and equity holders' claim is not reduced by the firm's
borrowings in the sense that subtraction implies. On TSMC the error is nearly
invisible -- D/(D+E) of 2.78% against a correct 2.71%, WACC 7.5827% against
7.5858% -- which is exactly why it survives review. On a name carrying real
leverage it moves the answer. Framework 4.3 states the rule; whether a given
model honours it is a `Conventions` field, so this module implements both and
the audit reports which one was used.

**The cost of debt is marginal, not historical.** Issue-level spreads or CDS,
not book interest expense, which reflects whatever the treasurer happened to
issue years ago. The fixture handles this well -- an average yield to maturity
across fifteen outstanding bonds -- and it is the one part of that model this
engine has no criticism of.
"""
from dataclasses import dataclass
from decimal import Decimal

from src.valuation.inputs import (
    EQUITY_WEIGHT_MARKET_CAP,
    EQUITY_WEIGHT_MARKET_CAP_LESS_DEBT,
    Conventions,
    ValuationInputs,
)
from src.valuation.money import divide


class CapitalStructureError(ValueError):
    """The capital structure cannot carry a weighting."""


@dataclass(frozen=True)
class CostOfCapital:
    """A WACC and every intermediate needed to check it by hand."""

    beta: Decimal
    cost_of_equity: Decimal
    cost_of_debt: Decimal
    after_tax_cost_of_debt: Decimal
    equity_value: Decimal           # whatever the convention treats as equity
    debt_value: Decimal
    equity_weight: Decimal
    debt_weight: Decimal
    wacc: Decimal
    equity_weight_basis: str

    def render(self) -> str:
        from src.valuation.money import as_percent
        return (
            f"WACC {as_percent(self.wacc, '0.0001')}%  "
            f"= CoE {as_percent(self.cost_of_equity, '0.0001')}% x "
            f"{as_percent(self.equity_weight)}% "
            f"+ CoD(after tax) {as_percent(self.after_tax_cost_of_debt, '0.0001')}% x "
            f"{as_percent(self.debt_weight)}%  "
            f"[equity weight: {self.equity_weight_basis}]")


def capm_cost_of_equity(risk_free_rate: Decimal, beta: Decimal,
                        equity_risk_premium: Decimal) -> Decimal:
    """rf + beta x ERP. The ERP is chosen and justified, never inherited (4.3)."""
    return risk_free_rate + beta * equity_risk_premium


def equity_weighting_value(inputs: ValuationInputs, basis: str) -> Decimal:
    """The quantity a model treats as the equity side of the capital structure."""
    if basis == EQUITY_WEIGHT_MARKET_CAP:
        return inputs.market_capitalisation
    if basis == EQUITY_WEIGHT_MARKET_CAP_LESS_DEBT:
        # Defect 6. Reproduced, never endorsed: the audit names it Class A.
        return inputs.market_capitalisation - inputs.gross_debt
    raise CapitalStructureError(f"unknown equity weight basis {basis!r}")


def cost_of_capital(inputs: ValuationInputs,
                    conventions: Conventions = Conventions.SPEC) -> CostOfCapital:
    """WACC from declared inputs, under the stated capital-structure convention."""
    equity = equity_weighting_value(inputs, conventions.equity_weight_basis)
    debt = inputs.gross_debt
    total = equity + debt
    if total <= 0:
        raise CapitalStructureError(
            f"capital structure sums to {total}: no weighting is defined")

    debt_weight = divide(debt, total)
    equity_weight = Decimal(1) - debt_weight
    cost_of_equity = capm_cost_of_equity(
        inputs.risk_free_rate, inputs.beta, inputs.equity_risk_premium)
    after_tax_cost_of_debt = inputs.cost_of_debt * (Decimal(1) - inputs.tax_rate)

    return CostOfCapital(
        beta=inputs.beta,
        cost_of_equity=cost_of_equity,
        cost_of_debt=inputs.cost_of_debt,
        after_tax_cost_of_debt=after_tax_cost_of_debt,
        equity_value=equity,
        debt_value=debt,
        equity_weight=equity_weight,
        debt_weight=debt_weight,
        wacc=cost_of_equity * equity_weight + after_tax_cost_of_debt * debt_weight,
        equity_weight_basis=conventions.equity_weight_basis,
    )
