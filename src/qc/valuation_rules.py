"""P2.6 — the framework 4 rules, evaluated against a model.

Each function here answers one rule and returns a `Finding` or `None`. None of
them decides anything: whether a finding blocks is `findings.FindingSet`'s
business, and whether it *can* be excepted was settled by its class in
`rules.py`. Keeping the evaluation dumb is what makes the class boundary hold.

Conventions -> findings
-----------------------
Defects 1, 6 and 7 are convention divergences, and they are detected by diffing
the conventions a workbook implements against `Conventions.SPEC` rather than by
three bespoke checks. That is worth stating plainly because it is the reason
this layer is maintainable: adding a convention adds a rule and a diff entry,
and a model cannot quietly implement a fourth defective behaviour that nobody
wrote a checker for.

Every finding carries its evidence -- the offending formula, and the material
consequence in the model's own units. "Terminal value is wrong" is not
actionable. "B18 is `=N16*(1+B17)/(B13-B17)` where N16 is the discounted 2030
UFCF; correcting it moves the target from TWD 1,732.66 to TWD 2,359.34" is.
"""
from decimal import Decimal

from src.qc.findings import Finding, Measurement
from src.qc.rules import rule
from src.valuation.dcf import DcfResult
from src.valuation.inputs import (
    EQUITY_WEIGHT_MARKET_CAP,
    EQUITY_WEIGHT_MARKET_CAP_LESS_DEBT,
    STUB_FULL_YEAR_AT_STUB_FACTOR,
    TV_FROM_DISCOUNTED_UFCF,
)
from src.valuation.money import as_percent, quantize_price
from src.valuation.wacc import cost_of_capital

#: Framework 4.6. A single hard threshold; the v1.0 non-blocking 70% tier was
#: deleted because a tier that cannot block is a warning by another name.
TERMINAL_VALUE_SHARE_LIMIT = Decimal("0.75")
#: Framework 4.6. Below this the model is a terminal-value assumption wearing
#: a DCF as a disguise.
WACC_GROWTH_SPREAD_FLOOR = Decimal("0.04")


def terminal_value_base_finding(model, as_built: DcfResult,
                                corrected: DcfResult) -> Finding | None:
    """Defect 1 — terminal value built from an already-discounted cash flow.

    Invisible in every value the workbook displays: the arithmetic is ordinary
    and the output lands in a believable range. The only evidence is that the
    formula names the discounted row.
    """
    if model.conventions.terminal_value_base != TV_FROM_DISCOUNTED_UFCF:
        return None

    m = model.cell_map
    cell = m.cell_terminal_value
    final, currency = m.columns[-1], model.inputs.currency
    return Finding(
        rule=rule("terminal_value_from_discounted_flow"),
        detail=(
            f"terminal value at {cell} is `{model.formula(cell)}`, built from "
            f"{final}{m.row_discounted_ufcf} — the already-discounted final "
            f"cash flow, not {final}{m.row_ufcf}. The final period's factor is "
            f"applied twice. Correcting it alone moves the target from "
            f"{currency} {quantize_price(as_built.share_price):,} to "
            f"{currency} {quantize_price(corrected.share_price):,}"),
        measured=corrected.share_price,
    )


def equity_weight_finding(model) -> Finding | None:
    """Defect 6 — equity weight is not market capitalisation.

    Numerically small on a lightly levered name, which is exactly why it
    survives review; conceptually it is not a defined quantity at all. Market
    capitalisation IS the market value of equity, and equity holders' claim is
    not reduced by the firm's borrowings in the sense subtraction implies.
    """
    if model.conventions.equity_weight_basis != EQUITY_WEIGHT_MARKET_CAP_LESS_DEBT:
        return None

    cell = model.cell_map.cell_equity_weight
    as_built = cost_of_capital(model.inputs, model.conventions)
    correct = cost_of_capital(
        model.inputs,
        type(model.conventions)(
            terminal_value_base=model.conventions.terminal_value_base,
            equity_weight_basis=EQUITY_WEIGHT_MARKET_CAP,
            stub_policy=model.conventions.stub_policy))
    return Finding(
        rule=rule("equity_weight_not_market_cap"),
        detail=(
            f"equity weight at {cell} is `{model.formula(cell)}`, netting debt "
            f"out of market capitalisation. D/(D+E) "
            f"{as_percent(as_built.debt_weight)}% against "
            f"{as_percent(correct.debt_weight)}% on market cap; WACC "
            f"{as_percent(as_built.wacc, '0.0001')}% against "
            f"{as_percent(correct.wacc, '0.0001')}%. Small here, material on a "
            f"levered name"),
        measured=as_built.debt_weight,
    )


def stub_period_finding(model) -> Finding | None:
    """Defect 7 — a full period of cash flow at a partial-period factor.

    Twelve months of cash for two months of waiting. Either count the fraction
    of the period that remains, or discount a full period at a full-period
    factor (framework 4.5, added at spec v1.2).
    """
    if model.conventions.stub_policy != STUB_FULL_YEAR_AT_STUB_FACTOR:
        return None

    m = model.cell_map
    first = m.columns[0]
    fraction = model.inputs.stub_fraction
    return Finding(
        rule=rule("stub_period_overstates_cash_flow"),
        detail=(
            f"discount factor at {first}{m.row_discount_factor} is "
            f"`{model.formula(f'{first}{m.row_discount_factor}')}`, a "
            f"{as_percent(fraction)}% stub, while "
            f"{first}{m.row_discounted_ufcf} is "
            f"`{model.formula(f'{first}{m.row_discounted_ufcf}')}` — the whole "
            f"period's cash flow. Either pro-rate the cash flow or discount a "
            f"full period at a full-period factor"),
        measured=fraction,
    )


def convention_findings(model, as_built: DcfResult,
                        corrected: DcfResult) -> list[Finding]:
    """Every finding that follows from how the workbook's formulas are built."""
    candidates = (
        terminal_value_base_finding(model, as_built, corrected),
        equity_weight_finding(model),
        stub_period_finding(model),
    )
    return [f for f in candidates if f is not None]


def terminal_value_share_measurement(result: DcfResult,
                                     label: str = "Terminal value share"
                                     ) -> Measurement:
    """Reported on every run, pass or fail (framework 4.6).

    Not a finding and not a warning tier: a measurement makes no claim about
    acceptability, it states a value. The threshold is shown beside it so a
    reader can see where the value sits without the gate having to editorialise.
    """
    return Measurement(
        label=label, value=as_percent(result.terminal_value_share), unit="%",
        spec_ref="4.6", threshold=as_percent(TERMINAL_VALUE_SHARE_LIMIT))


def wacc_growth_spread_measurement(result: DcfResult) -> Measurement:
    """The spread, diagnostic on every run (framework 4.4, 4.6)."""
    return Measurement(
        label="WACC less terminal growth",
        value=as_percent(result.spread_to_terminal_growth), unit="pp",
        spec_ref="4.6", threshold=as_percent(WACC_GROWTH_SPREAD_FLOOR))
