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
from src.valuation.money import as_percent, divide, quantize_price
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


# --------------------------------------------------------------------------
# Provenance rules — defects 4 and 5 (framework 6.4, 4.4, 4.6)
#
# Neither defect is visible in any arithmetic. 0.0445 is a perfectly ordinary
# number to multiply by, and 1.22 is a perfectly ordinary beta; nothing about
# either computation is unusual. What is missing is a declaration of where the
# number came from, so both resolve through the provenance machinery Phase 1
# already built rather than through anything new.
#
# The unit vocabulary below is the one implementation choice here that the
# framework does not spell out. 6.4 requires a declared unit and says scale is
# read and never inferred; it does not enumerate the units a rate may carry.
# A closed pair of tuples keeps the check honest -- an unrecognised unit fails
# rather than passing by default, which is the whole point of not inferring.
# --------------------------------------------------------------------------

#: A growth rate that may be applied to nominal cash flows.
NOMINAL_RATE_UNITS = ("nominal_rate", "nominal_growth", "nominal_gdp_growth")
#: A growth rate that may not. Applying one to nominal flows is defect 4.
REAL_RATE_UNITS = ("real_rate", "real_growth", "real_gdp_growth")


def _handle(inputs, field: str) -> tuple[str, str] | None:
    """Split a provenance handle into (kind, key), or None if undeclared."""
    raw = inputs.provenance.get(field)
    if not raw:
        return None
    kind, _, key = str(raw).partition(":")
    return (kind, key) if key else ("", str(raw))


def terminal_growth_provenance_finding(inputs, externals: dict | None = None
                                       ) -> Finding | None:
    """Defect 4 — a real growth rate applied to nominal cash flows.

    The DCF discounts nominal cash flows, so the perpetuity growth rate must be
    nominal too. A real GDP figure is a unit mismatch in either direction, and
    no amount of recomputation reveals it: the arithmetic is identical. Only a
    declared unit can settle it.
    """
    externals = externals or {}
    growth = as_percent(inputs.terminal_growth)
    handle = _handle(inputs, "terminal_growth")

    if handle is None:
        return Finding(
            rule=rule("real_growth_on_nominal_flows"),
            detail=(
                f"terminal growth {growth}% carries no declared provenance, so "
                f"it cannot be shown to be a nominal rate. The forecast "
                f"discounts nominal cash flows; a real rate here is a unit "
                f"mismatch that no recomputation would reveal"),
            measured=inputs.terminal_growth)

    kind, key = handle
    if kind != "ext":
        # A derived or facts-table figure carries its unit through Phase 1's
        # resolver, which checks unit compatibility already.
        return None

    record = externals.get(key)
    if record is None:
        return Finding(
            rule=rule("real_growth_on_nominal_flows"),
            detail=(f"terminal growth {growth}% cites external record {key!r}, "
                    f"which is not in the store"),
            measured=inputs.terminal_growth)

    if record.unit in REAL_RATE_UNITS:
        return Finding(
            rule=rule("real_growth_on_nominal_flows"),
            detail=(
                f"terminal growth {growth}% is declared as {record.unit!r} "
                f"({record.source}) and applied to nominal cash flows. Use a "
                f"nominal long-run growth rate, or deflate the forecast"),
            measured=inputs.terminal_growth)

    if record.unit not in NOMINAL_RATE_UNITS:
        return Finding(
            rule=rule("real_growth_on_nominal_flows"),
            detail=(
                f"terminal growth {growth}% is declared with unit "
                f"{record.unit!r}, which is neither nominal nor real. Scale and "
                f"unit are read, never inferred (6.4); legal nominal units are "
                f"{NOMINAL_RATE_UNITS}"),
            measured=inputs.terminal_growth)

    return None


def beta_provenance_finding(inputs, externals: dict | None = None
                            ) -> Finding | None:
    """Defect 5 — beta taken from a terminal rather than computed.

    Note what is and is not prohibited. `external.py` legitimately permits a
    `beta_input` record: regression inputs and peer betas are exactly the kind
    of thing the facts table cannot answer, and they SHOULD be declared that
    way. The violation is using such a record *directly as the beta* instead of
    as an input to a computation. 4.4 requires the beta derived -- peer-median
    unlevered, relevered to target structure, with a regression beta computed
    alongside and the spread shown -- and a derived figure is a model cell.
    """
    externals = externals or {}
    handle = _handle(inputs, "beta")

    if handle is None:
        return Finding(
            rule=rule("beta_not_derived"),
            detail=(
                f"beta {inputs.beta} carries no declared provenance. 4.4 "
                f"requires it computed both ways -- peer-median unlevered "
                f"relevered to target structure, and a regression beta "
                f"alongside, with the spread shown -- not asserted"),
            measured=inputs.beta)

    kind, key = handle
    if kind == "ext":
        record = externals.get(key)
        source = f" ({record.source})" if record is not None else ""
        return Finding(
            rule=rule("beta_not_derived"),
            detail=(
                f"beta {inputs.beta} is taken directly from external record "
                f"{key!r}{source}. A beta_input record is an INPUT to a beta "
                f"computation, not the beta: 4.4 requires peer-median "
                f"unlevered relevered, with the regression beta and the spread "
                f"reported alongside"),
            measured=inputs.beta)

    return None


def provenance_findings(inputs, externals: dict | None = None) -> list[Finding]:
    """Defects 4 and 5: figures whose problem is what was never declared."""
    candidates = (terminal_growth_provenance_finding(inputs, externals),
                  beta_provenance_finding(inputs, externals))
    return [f for f in candidates if f is not None]


# --------------------------------------------------------------------------
# Threshold rules — defects 2 and 3 (framework 4.6). Both Class B.
#
# These are the first rules in the registry that a declared exception can
# satisfy, and the reason they are Class B rather than Class A is worth being
# precise about. A terminal value at 86.8% of enterprise value is not WRONG.
# It is unusual, and on an infrastructure concession or a pre-revenue biotech
# it can be entirely honest. What it cannot be is unremarked.
#
# They are measured on the TV-corrected run, not the as-built one, because the
# corrected run is the honest statement of what this model implies.
#
# Note what the fixture does and does not show. As built, terminal value is
# 81.8% of enterprise value -- already above the 75% threshold, so this rule
# fires on the published model too. The arithmetic error did not hide the
# breach; it understated it, to 81.8% from a true 86.8%. That is a weaker
# claim than "the error concealed the condition" and it is the accurate one.
# The masking that matters is of the target price: TWD 1,732.66 against
# TWD 2,359.34, a 36% understatement landing in a believable range.
# --------------------------------------------------------------------------

def terminal_value_share_finding(corrected: DcfResult,
                                 as_built: DcfResult | None = None,
                                 sensitivity: tuple | None = None
                                 ) -> Finding | None:
    """Defect 2 — terminal value above 75% of enterprise value (4.6)."""
    share = corrected.terminal_value_share
    if share <= TERMINAL_VALUE_SHARE_LIMIT:
        return None

    detail = (f"terminal value is {as_percent(share)}% of enterprise value, "
              f"above the {as_percent(TERMINAL_VALUE_SHARE_LIMIT)}% threshold")
    if as_built is not None and as_built.terminal_value_share < share:
        detail += (f". As built it reads "
                   f"{as_percent(as_built.terminal_value_share)}%: the "
                   f"arithmetic error understated the dominance")
    if sensitivity is not None:
        down, up = sensitivity
        currency = corrected.inputs.currency
        swing = divide(up.share_price - down.share_price, corrected.share_price)
        detail += (f". A +/-50bp band on g moves the target from {currency} "
                   f"{quantize_price(down.share_price):,} to {currency} "
                   f"{quantize_price(up.share_price):,}, {as_percent(swing)}% "
                   f"of the value being defended")
    return Finding(rule=rule("terminal_value_share"), detail=detail,
                   measured=share, threshold=TERMINAL_VALUE_SHARE_LIMIT)


def wacc_growth_spread_finding(result: DcfResult) -> Finding | None:
    """Defect 3 — WACC minus g below 4 percentage points (4.6)."""
    spread = result.spread_to_terminal_growth
    if spread >= WACC_GROWTH_SPREAD_FLOOR:
        return None

    return Finding(
        rule=rule("wacc_growth_spread"),
        detail=(
            f"WACC less terminal growth is {as_percent(spread)}pp, below the "
            f"{as_percent(WACC_GROWTH_SPREAD_FLOOR)}pp floor "
            f"(WACC {as_percent(result.wacc, '0.0001')}%, g "
            f"{as_percent(result.terminal_growth)}%). Below this the model is a "
            f"terminal-value assumption wearing a DCF as a disguise"),
        measured=spread, threshold=WACC_GROWTH_SPREAD_FLOOR)


def threshold_findings(corrected: DcfResult,
                       as_built: DcfResult | None = None,
                       sensitivity: tuple | None = None) -> list[Finding]:
    """Defects 2 and 3, evaluated on the corrected model."""
    candidates = (terminal_value_share_finding(corrected, as_built, sensitivity),
                  wacc_growth_spread_finding(corrected))
    return [f for f in candidates if f is not None]


def growth_sensitivity_measurements(result: DcfResult,
                                    sensitivity: tuple) -> list[Measurement]:
    """Target price at g -/+ 50bp, reported alongside every DCF (4.6)."""
    down, up = sensitivity
    currency = result.inputs.currency
    return [
        Measurement(label=f"Target at g -50bp "
                          f"({as_percent(down.inputs.terminal_growth)}%), {currency}",
                    value=quantize_price(down.share_price), spec_ref="4.6"),
        Measurement(label=f"Target at g +50bp "
                          f"({as_percent(up.inputs.terminal_growth)}%), {currency}",
                    value=quantize_price(up.share_price), spec_ref="4.6"),
    ]


# --------------------------------------------------------------------------
# Completeness — defect 8 (framework 4.2, 4.7, 4.10). Class B.
#
# "Assign 100% weight on DCF approach" is the fixture's own note, and 4.2
# forbids it: always triangulate, and explain why the methods disagree, because
# the reconciliation is usually more informative than any single output.
#
# On a model whose valuation is 87% terminal value, a comps cross-check is not
# a nicety. It is the only thing standing between the model and an
# unfalsifiable number: every input to the perpetuity is an assumption, so
# nothing inside the DCF can contradict the DCF.
#
# Class B rather than Class A, and the line is worth being careful about. A
# single-method valuation is unusual, not arithmetically wrong -- there are
# names with no usable comp set at all, and for those an exception is the
# honest route. Nothing here says the number is incorrect.
# --------------------------------------------------------------------------

#: Framework 4.2: never assign 100% weight to a single method.
MINIMUM_VALUATION_METHODS = 2

_COMPONENT_NAMES = {
    "dcf": "a DCF",
    "comparable_companies": "comparable companies",
    "reverse_dcf": "a reverse DCF",
    "scenarios": "scenarios",
    "sensitivity": "a sensitivity table",
}


def completeness_finding(model) -> Finding | None:
    """Defect 8 — single-method valuation, and what else is missing."""
    from src.valuation.excel.reader import VALUATION_COMPONENTS

    present = set(model.cell_map.components)
    missing = [c for c in VALUATION_COMPONENTS if c not in present]
    dead = model.dead_rows

    if len(present) >= MINIMUM_VALUATION_METHODS and not missing:
        return None

    detail = (
        f"the valuation rests on "
        f"{', '.join(_COMPONENT_NAMES.get(c, c) for c in sorted(present))} "
        f"alone. 4.2 requires triangulation across at least "
        f"{MINIMUM_VALUATION_METHODS} methods and forbids 100% weight on one. "
        f"Missing: {', '.join(_COMPONENT_NAMES.get(c, c) for c in missing)}")
    if dead:
        rows = ", ".join(str(r) for r in dead)
        detail += (f". Row {rows} is computed for every period and read by no "
                   f"other formula -- a dead line, and a divergence risk the "
                   f"moment either it or the live model is edited")
    return Finding(rule=rule("single_method_valuation"), detail=detail,
                   measured=Decimal(len(present)),
                   threshold=Decimal(MINIMUM_VALUATION_METHODS))
