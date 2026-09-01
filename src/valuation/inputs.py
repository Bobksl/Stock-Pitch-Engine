"""P2.2 — the declared inputs of a valuation, and the conventions applied to them.

Two dataclasses, and the split between them is the load-bearing idea.

`ValuationInputs` is *what the analyst asserted*: a risk-free rate, a beta, a
margin path, a terminal growth rate. Numbers.

`Conventions` is *how those numbers are combined* -- which cash flow the
terminal value is built from, what counts as the equity weight, how a stub
period is discounted. Not numbers, and not opinions either: each field has one
answer the framework endorses and at least one that a real model in the wild
actually uses instead.

Keeping them apart is what lets a single engine produce both halves of Audit
section 2's table. Run the TSMC fixture's own inputs under the conventions the
workbook actually implements and you get its published TWD 1,732.66; run the
identical inputs under `Conventions.SPEC` and you get TWD 2,359.34. The
difference between the two runs is not a pile of special cases, it is a diff
of three enumerated fields -- and each field that differs from SPEC is exactly
one Audit finding. The defect list falls out of comparing conventions rather
than being hand-maintained alongside them.

Defect numbering throughout Phase 2 follows the eight-row exit-criterion table,
which is what the acceptance test asserts against. The audit's own section 2
headings number differently -- it folds terminal-value share and the
WACC-minus-g spread into a single "Finding 2" -- so its later references are
offset by one. The mapping between the two lives in src/qc/rules.py, once.

Defects 4 and 5 (a real growth rate on nominal flows; a beta lifted from a
terminal) are deliberately *not* conventions. Nothing about the arithmetic is
unusual in either case -- 0.0445 is a perfectly ordinary number to multiply
by. What is missing is a declaration of where it came from, so they resolve
through the framework 6.4 provenance machinery Phase 1 already built, via
`provenance` below, rather than through a fourth convention field.
"""
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Mapping

# --------------------------------------------------------------------------
# Convention vocabularies. Each is closed, and the first entry is the one
# framework section 4 endorses; the others exist because real models use them.
# --------------------------------------------------------------------------

#: Terminal value is built from the final year's *undiscounted* free cash flow
#: and the result discounted once. (Framework 4.6.)
TV_FROM_UNDISCOUNTED_UFCF = "undiscounted_final_ufcf"
#: ...from the already-discounted final cash flow, and then discounted again.
#: Defect 1: a ~36% error, and Class A -- this is wrong, not unusual.
TV_FROM_DISCOUNTED_UFCF = "discounted_final_ufcf"

#: Equity weight in the capital structure is market capitalisation.
#: (Framework 4.3: "do not net debt out of market cap".)
EQUITY_WEIGHT_MARKET_CAP = "market_cap"
#: ...is market capitalisation minus debt. Defect 6, Class A: not a defined
#: quantity. Numerically small on TSMC, material on a levered name.
EQUITY_WEIGHT_MARKET_CAP_LESS_DEBT = "market_cap_less_debt"

#: A partial first period discounts a pro-rated slice of that period's cash
#: flow at the matching partial-period factor.
STUB_PRORATE_CASH_FLOW = "prorate_cash_flow"
#: ...discounts the *full* year's cash flow at the partial-period factor,
#: collecting twelve months of cash for two months of waiting. Defect 7.
STUB_FULL_YEAR_AT_STUB_FACTOR = "full_year_at_stub_factor"


@dataclass(frozen=True)
class Conventions:
    """How the inputs are combined. Every field is an enumerated choice."""

    terminal_value_base: str = TV_FROM_UNDISCOUNTED_UFCF
    equity_weight_basis: str = EQUITY_WEIGHT_MARKET_CAP
    stub_policy: str = STUB_PRORATE_CASH_FLOW

    def divergences(self, other: "Conventions") -> tuple[str, ...]:
        """Field names where `self` differs from `other`, in declaration order."""
        return tuple(f.name for f in self.__dataclass_fields__.values()
                     if getattr(self, f.name) != getattr(other, f.name))


#: The conventions framework section 4 requires. A model is compared against
#: this, and each divergence is a finding.
Conventions.SPEC = Conventions()


@dataclass(frozen=True)
class ForecastYear:
    """One explicit-forecast period's drivers.

    Framework 4.5: these are the Section 3 bridge components, not independent
    assumptions. Phase 2 computes with them; the C3 consistency check that
    they equal the bridge is wired when Section 3 exists.
    """

    period: int
    revenue_growth: Decimal
    ebitda_margin: Decimal
    depreciation: Decimal
    capex: Decimal                      # negative: an outflow
    change_in_nwc: Decimal              # negative: an investment
    gross_margin: Decimal | None = None # modelled by some workbooks, unused in UFCF


@dataclass(frozen=True)
class ValuationInputs:
    """Everything the analyst asserted, before any convention is applied."""

    currency: str
    unit: str                           # 'billion', 'million', ... never inferred (6.4)

    # Explicit forecast
    base_period: int
    base_revenue: Decimal
    forecast: tuple[ForecastYear, ...]

    # Cost of equity (4.3)
    risk_free_rate: Decimal
    equity_risk_premium: Decimal
    beta: Decimal

    # Cost of debt and tax (4.3)
    cost_of_debt: Decimal
    tax_rate: Decimal

    # Capital structure (4.3). Market cap is the equity weight; whether a model
    # honours that is a Convention, not an input.
    market_capitalisation: Decimal
    gross_debt: Decimal

    # Terminal value (4.6)
    terminal_growth: Decimal

    # Equity bridge (4.9)
    total_debt: Decimal                 # negative: subtracted from EV
    cash_and_equivalents: Decimal
    shares_outstanding: Decimal

    #: Fraction of the first forecast period that remains unelapsed at the
    #: valuation date. 1 means a full year. TSMC's model uses 1/6 (~2 months).
    stub_fraction: Decimal = Decimal(1)

    #: Field name -> provenance handle (a citation anchor or external record
    #: key), exactly as framework 6.4 requires of every figure. An input absent
    #: from this mapping is undeclared, which is a failure and not a default:
    #: it is how defects 4 and 5 are detected.
    provenance: Mapping[str, str] = field(default_factory=dict)

    @property
    def horizon(self) -> int:
        return len(self.forecast)

    def undeclared(self, required: tuple[str, ...]) -> tuple[str, ...]:
        """Those of `required` carrying no provenance handle."""
        return tuple(name for name in required if not self.provenance.get(name))
