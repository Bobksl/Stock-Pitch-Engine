"""P2.12 — comparable company analysis (framework 4.8).

Four things this module refuses to let a reader skip.

**The pairing rule is a hard error, not a warning.** Enterprise value pairs
with pre-interest metrics -- sales, EBITDA, EBIT -- because those flows are
available to every provider of capital. Equity value pairs with post-interest
metrics -- earnings, FCFE, book -- because those are what is left for equity.
EV/earnings is not a conservative multiple or an aggressive one; it is a ratio
of two things measured at different points in the capital structure, and it
means nothing. So it raises.

**The multiple is a function of the business model.** Software trades above
hardware because of a structurally better margin trajectory, lower capital
intensity and a longer runway -- not sentiment. Two consequences follow, and
both are implemented: a model implying a multiple outside the peer
distribution must be justified in writing, and a re-rating thesis needs a
business-model change behind it rather than a change of mood.

**Growth-adjusted multiples are a cross-check, never the method.** Dividing a
multiple by growth is PEG's problems transplanted: linear in growth, blind to
margin structure, scale and retention. Two companies growing 25% with
different terminal margins do not deserve the same EV/Sales. The primary
method is a regression of the multiple on growth and a profitability measure
across a wide comp set, reading the residual -- which is what `regress` does,
and `growth_adjusted` is offered beside it with its status in the name.

**Anchor disclosure is mandatory.** This is the one that changes conclusions.
Reddit at IPO, from the source write-up: growth-adjusted, PINS 5.0/19 =
0.263x, SNAP 3.6/16 = 0.225x. Anchor to PINS and the implied multiple is
6.58x, a target of $41.43-44.10, 22-30% upside. Anchor to SNAP and it is
5.62x, $36.76, +8%. Same method, same inputs, same day -- and the headline is
roughly three times larger purely because of which peer was picked. The source
never flags the choice. So `anchor_disclosure` returns EVERY anchor and the
full resulting range, and a valuation that reports one anchor without the
range fails `anchor_range_not_disclosed` (Class A).
"""
from dataclasses import dataclass
from decimal import Decimal

from src.valuation.money import D, divide

# --------------------------------------------------------------------------
# Numerators and metrics. The pairing between them is the point.
# --------------------------------------------------------------------------

NUMERATOR_ENTERPRISE = "enterprise_value"
NUMERATOR_EQUITY = "equity_value"

METRIC_SALES = "sales"
METRIC_EBITDA = "ebitda"
METRIC_EBIT = "ebit"
METRIC_EARNINGS = "earnings"
METRIC_FCFE = "fcfe"
METRIC_BOOK = "book_value"

#: Framework 4.8. Pre-interest metrics belong to every capital provider and so
#: pair with enterprise value; post-interest metrics belong to equity alone.
#: "P/FCF" in the selection tree is equity value over FCFE -- a levered cash
#: flow -- which is why FCFE sits on the equity side and no unlevered
#: free-cash-flow metric is offered here at all.
PAIRING: dict[str, tuple[str, ...]] = {
    NUMERATOR_ENTERPRISE: (METRIC_SALES, METRIC_EBITDA, METRIC_EBIT),
    NUMERATOR_EQUITY: (METRIC_EARNINGS, METRIC_FCFE, METRIC_BOOK),
}

_LABELS = {
    (NUMERATOR_ENTERPRISE, METRIC_SALES): "EV/Sales",
    (NUMERATOR_ENTERPRISE, METRIC_EBITDA): "EV/EBITDA",
    (NUMERATOR_ENTERPRISE, METRIC_EBIT): "EV/EBIT",
    (NUMERATOR_EQUITY, METRIC_EARNINGS): "P/E",
    (NUMERATOR_EQUITY, METRIC_FCFE): "P/FCF",
    (NUMERATOR_EQUITY, METRIC_BOOK): "P/B",
}

#: Framework 4.8 requires a minimum and does not name a number: "n=2 is a
#: teaching example, not a valuation". Five is the choice made here -- enough
#: that a median is not one opinion and a two-regressor regression has degrees
#: of freedom left. It is a Class B rule, so a genuinely thin sub-industry can
#: carry a declared exception rather than being unvaluable.
MINIMUM_COMP_SET = 5


class PairingError(ValueError):
    """A numerator and a metric measured at different points of the structure."""


class CompSetError(ValueError):
    """The comp set is inconsistent, too small, or unusable."""


def label(numerator: str, metric: str) -> str:
    return _LABELS.get((numerator, metric), f"{numerator}/{metric}")


def check_pairing(numerator: str, metric: str) -> None:
    """Raise unless the two are measured at the same point in the structure."""
    if numerator not in PAIRING:
        raise PairingError(f"unknown numerator {numerator!r}")
    if metric not in PAIRING[numerator]:
        other = (NUMERATOR_EQUITY if numerator == NUMERATOR_ENTERPRISE
                 else NUMERATOR_ENTERPRISE)
        hint = (f" -- {metric!r} is a {other.replace('_', ' ')} metric"
                if metric in PAIRING[other] else "")
        raise PairingError(
            f"{numerator} does not pair with {metric}{hint}. Enterprise value "
            f"pairs with {PAIRING[NUMERATOR_ENTERPRISE]}; equity value pairs "
            f"with {PAIRING[NUMERATOR_EQUITY]} (framework 4.8).")


# --------------------------------------------------------------------------
# Metric selection (framework 4.8 decision tree)
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class TargetProfile:
    """The facts that decide which multiple is the right one."""

    profitable: bool
    depreciation_material: bool
    high_growth_long_runway: bool = False
    earnings_distorted_by_reinvestment: bool = False
    is_financial: bool = False


def select_metric(profile: TargetProfile) -> tuple[str, str]:
    """The (numerator, metric) framework 4.8 prescribes for this profile.

    The spec presents an unordered table; the order below is the reading that
    makes it total. Financials come first because their treatment is a
    different regime rather than a different row -- interest is operating, not
    financing, so every enterprise-value multiple is meaningless for them, and
    that override cannot sit below a profitability test it would contradict.
    Reinvestment distortion comes next, because it is a statement that the
    earnings-based rows would be measuring something misleading.
    """
    if profile.is_financial:
        return NUMERATOR_EQUITY, METRIC_EARNINGS
    if profile.earnings_distorted_by_reinvestment:
        return NUMERATOR_EQUITY, METRIC_FCFE
    if profile.profitable:
        return ((NUMERATOR_ENTERPRISE, METRIC_EBITDA)
                if profile.depreciation_material
                else (NUMERATOR_ENTERPRISE, METRIC_EBIT))
    if profile.high_growth_long_runway:
        # Explicitly a placeholder; graduates to EV/EBITDA once margins arrive.
        return NUMERATOR_ENTERPRISE, METRIC_SALES
    raise CompSetError(
        "unprofitable, without a long growth runway, and not reinvestment "
        "distorted: framework 4.8 prescribes no multiple for this profile. "
        "A relative valuation here would be a number with no argument behind "
        "it.")


# --------------------------------------------------------------------------
# The comp set
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class Peer:
    """One comparable, on the same basis as every other (framework 4.8)."""

    ticker: str
    numerator_value: Decimal        # EV or equity value, matching `numerator`
    metric_value: Decimal           # the denominator
    growth: Decimal                 # forward growth, as a fraction
    profitability: Decimal | None = None    # margin, Rule of 40, ...
    period: str = ""                # calendar period the estimates cover
    estimate_source: str = ""       # who produced them

    def multiple(self) -> Decimal:
        if self.metric_value == 0:
            raise CompSetError(f"{self.ticker}: metric is zero")
        return divide(self.numerator_value, self.metric_value)

    @property
    def growth_points(self) -> Decimal:
        """Growth in percentage points, which is how the ratio is quoted."""
        return self.growth * 100

    def growth_adjusted(self) -> Decimal:
        """Multiple per point of growth. A CROSS-CHECK, never the method.

        PEG's problems transplanted: linear in growth, blind to margin
        structure, scale and retention.
        """
        if self.growth_points == 0:
            raise CompSetError(f"{self.ticker}: zero growth, no adjusted multiple")
        return divide(self.multiple(), self.growth_points)


def validate_comp_set(peers: tuple[Peer, ...], numerator: str, metric: str
                      ) -> None:
    """Consistency and size. Both are framework 4.8 requirements."""
    check_pairing(numerator, metric)
    if not peers:
        raise CompSetError("no peers")

    periods = {p.period for p in peers}
    if len(periods) > 1:
        raise CompSetError(
            f"peers cover different calendar periods {sorted(periods)}: a "
            f"multiple built across vintages compares nothing (framework 4.8)")
    sources = {p.estimate_source for p in peers}
    if len(sources) > 1:
        raise CompSetError(
            f"peers use different estimate sources {sorted(sources)}: "
            f"definitions differ between providers (framework 4.8)")


# --------------------------------------------------------------------------
# The primary method: regression, and the residual
# --------------------------------------------------------------------------

def _solve(matrix: list[list[Decimal]], vector: list[Decimal]) -> list[Decimal]:
    """Gaussian elimination with partial pivoting, in Decimal.

    Small and explicit rather than numpy, for the same reason the rest of the
    engine is Decimal: a regression whose coefficients came back through
    binary64 would be the one float in a chain that claims exactness.
    """
    size = len(vector)
    rows = [list(row) + [value] for row, value in zip(matrix, vector)]

    for column in range(size):
        pivot = max(range(column, size), key=lambda r: abs(rows[r][column]))
        if rows[pivot][column] == 0:
            raise CompSetError(
                "the regression is singular: the peers do not vary "
                "independently in growth and profitability, so no line through "
                "them is determined")
        rows[column], rows[pivot] = rows[pivot], rows[column]
        for other in range(size):
            if other == column:
                continue
            factor = divide(rows[other][column], rows[column][column])
            for position in range(column, size + 1):
                rows[other][position] -= factor * rows[column][position]

    return [divide(rows[i][size], rows[i][i]) for i in range(size)]


@dataclass(frozen=True)
class Regression:
    """The fitted relationship, and what each peer's residual says."""

    intercept: Decimal
    growth_coefficient: Decimal
    profitability_coefficient: Decimal | None
    fitted: dict[str, Decimal]
    residuals: dict[str, Decimal]

    def predict(self, growth: Decimal,
                profitability: Decimal | None = None) -> Decimal:
        value = self.intercept + self.growth_coefficient * growth
        if self.profitability_coefficient is not None:
            if profitability is None:
                raise CompSetError(
                    "this regression uses profitability; supply it to predict")
            value += self.profitability_coefficient * profitability
        return value

    def render(self) -> str:
        terms = [f"{self.intercept:.4f}",
                 f"{self.growth_coefficient:+.4f}·growth"]
        if self.profitability_coefficient is not None:
            terms.append(f"{self.profitability_coefficient:+.4f}·profitability")
        cheapest = min(self.residuals, key=self.residuals.get)
        dearest = max(self.residuals, key=self.residuals.get)
        return (f"multiple = {' '.join(terms)}   "
                f"cheapest residual {cheapest} ({self.residuals[cheapest]:+.3f}), "
                f"dearest {dearest} ({self.residuals[dearest]:+.3f})")


def regress(peers: tuple[Peer, ...], use_profitability: bool = True
            ) -> Regression:
    """Regress the multiple on growth and profitability; read the residual.

    The primary normalisation method (framework 4.8). The residual is the
    interesting output: it is what the peer trades at relative to what its own
    growth and profitability say it should, which is the closest thing a comp
    table offers to an argument.
    """
    if use_profitability and any(p.profitability is None for p in peers):
        use_profitability = False

    parameters = 3 if use_profitability else 2
    if len(peers) <= parameters:
        raise CompSetError(
            f"{len(peers)} peers cannot determine {parameters} regression "
            f"parameters. Fitting a line through as many points as it has "
            f"degrees of freedom describes the points, not the relationship.")

    rows = []
    for peer in peers:
        row = [D(1), peer.growth]
        if use_profitability:
            row.append(peer.profitability)
        rows.append(row)
    observations = [peer.multiple() for peer in peers]

    # Normal equations: (XᵀX)β = Xᵀy
    xtx = [[sum((row[i] * row[j] for row in rows), D(0))
            for j in range(parameters)] for i in range(parameters)]
    xty = [sum((row[i] * y for row, y in zip(rows, observations)), D(0))
           for i in range(parameters)]
    beta = _solve(xtx, xty)

    fitted, residuals = {}, {}
    for peer, row, actual in zip(peers, rows, observations):
        prediction = sum((b * x for b, x in zip(beta, row)), D(0))
        fitted[peer.ticker] = prediction
        residuals[peer.ticker] = actual - prediction

    return Regression(
        intercept=beta[0], growth_coefficient=beta[1],
        profitability_coefficient=beta[2] if use_profitability else None,
        fitted=fitted, residuals=residuals)


# --------------------------------------------------------------------------
# Anchor disclosure — mandatory (framework 4.8)
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class Anchor:
    """What the target is worth if THIS peer is the comparable."""

    peer: str
    peer_multiple: Decimal
    peer_growth_adjusted: Decimal
    implied_multiple: Decimal
    implied_numerator: Decimal      # implied EV or equity value
    implied_price: Decimal | None = None
    upside: Decimal | None = None


@dataclass(frozen=True)
class AnchorDisclosure:
    """Every anchor, and the range they span. Never one of them alone."""

    numerator: str
    metric: str
    anchors: tuple[Anchor, ...]

    @property
    def low(self) -> Anchor:
        return min(self.anchors, key=lambda a: a.implied_multiple)

    @property
    def high(self) -> Anchor:
        return max(self.anchors, key=lambda a: a.implied_multiple)

    @property
    def spread(self) -> Decimal:
        """High implied multiple over low. 1 means the choice did not matter."""
        return divide(self.high.implied_multiple, self.low.implied_multiple)

    def render(self, currency: str = "") -> str:
        lines = [f"Anchor disclosure — {label(self.numerator, self.metric)}, "
                 f"every peer (framework 4.8)"]
        for anchor in sorted(self.anchors, key=lambda a: a.implied_multiple):
            line = (f"  anchored to {anchor.peer}: "
                    f"{anchor.peer_growth_adjusted:.3f}x per point → "
                    f"{anchor.implied_multiple:.2f}x")
            if anchor.implied_price is not None:
                line += f" → {currency} {anchor.implied_price:.2f}"
            if anchor.upside is not None:
                line += f" ({anchor.upside * 100:+.1f}%)"
            lines.append(line)
        lines.append(f"  range {self.low.implied_multiple:.2f}x – "
                     f"{self.high.implied_multiple:.2f}x, "
                     f"a factor of {self.spread:.2f} on the choice of peer")
        return "\n".join(lines)


def anchor_disclosure(peers: tuple[Peer, ...], target_growth: Decimal,
                      target_metric_value: Decimal, numerator: str,
                      metric: str, net_debt: Decimal = Decimal(0),
                      shares: Decimal | None = None,
                      current_price: Decimal | None = None) -> AnchorDisclosure:
    """The implied value under EVERY peer anchor, and the resulting range.

    `net_debt` is subtracted from an enterprise-value numerator to reach equity
    (pass it signed as debt minus cash); it is ignored on the equity side,
    where the numerator is already an equity value.
    """
    validate_comp_set(peers, numerator, metric)
    target_growth_points = target_growth * 100

    anchors = []
    for peer in peers:
        adjusted = peer.growth_adjusted()
        implied_multiple = adjusted * target_growth_points
        implied_numerator = implied_multiple * target_metric_value

        implied_price = upside = None
        if shares is not None and shares > 0:
            equity = (implied_numerator - net_debt
                      if numerator == NUMERATOR_ENTERPRISE else implied_numerator)
            implied_price = divide(equity, shares)
            if current_price is not None and current_price > 0:
                upside = divide(implied_price, current_price) - Decimal(1)

        anchors.append(Anchor(
            peer=peer.ticker, peer_multiple=peer.multiple(),
            peer_growth_adjusted=adjusted, implied_multiple=implied_multiple,
            implied_numerator=implied_numerator, implied_price=implied_price,
            upside=upside))

    return AnchorDisclosure(numerator=numerator, metric=metric,
                            anchors=tuple(anchors))


def outside_peer_distribution(implied_multiple: Decimal,
                              peers: tuple[Peer, ...]) -> bool:
    """Whether a model-implied multiple sits outside the peer range.

    The sanity gate of framework 4.8: a multiple far outside the sub-industry
    distribution is not forbidden, it is a claim that requires justification in
    writing. The peer range is the test rather than a dispersion band because
    a comp set of five or six has no dispersion worth estimating.
    """
    multiples = [peer.multiple() for peer in peers]
    return implied_multiple < min(multiples) or implied_multiple > max(multiples)


@dataclass(frozen=True)
class CompsExport:
    """What the Comps tab needs: the peer table and the target's own figures.

    Separate from `AnchorDisclosure` on purpose. The disclosure is a computed
    result; this is the declared input the workbook recomputes it from, and
    keeping them apart is what stops the tab restating Python's answer instead
    of deriving it (the same distinction the Reverse DCF tab turns on).
    """

    peers: tuple[Peer, ...]
    numerator: str
    metric: str
    target_metric_value: Decimal
    target_growth: Decimal
    net_debt: Decimal = Decimal(0)
    current_price: Decimal | None = None

    def disclosure(self, shares: Decimal | None = None) -> AnchorDisclosure:
        return anchor_disclosure(
            self.peers, self.target_growth, self.target_metric_value,
            self.numerator, self.metric, net_debt=self.net_debt,
            shares=shares, current_price=self.current_price)
