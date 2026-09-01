"""P2.7 — beta, computed both ways (framework 4.4).

**Compute both; default to peer-median unlevered beta, relevered to target
structure.** That is the resolved policy, and the reasoning behind it is what
the code has to preserve.

A single-name regression beta is statistically noisy -- wide standard errors,
materially sensitive to window, frequency and index -- and contaminated by
idiosyncratic history that says nothing about *forward* business risk, which
is the only thing a discount rate needs to capture. Peer-median betas average
that noise away and isolate business risk. So the peer route is the default,
not a fallback.

Regression is preferred only when the name is large, liquid, long-listed and
genuinely lacks a comp set, or when the thesis is specifically that its risk
profile differs from peers. For a recent IPO a regression beta is not merely
noisy, it is unavailable, and peer-relevered is the only defensible choice.

**The spread is diagnostic and must be shown.** A regression beta well above
peer-relevered means the market prices the name as riskier than its business
model implies -- either a mispricing to exploit or something the fundamental
work missed. It belongs in the thesis discussion, not buried in a WACC tab, so
`BetaPolicy` carries it and `render()` always prints it.

Blume
-----
The adjustment (2/3 x beta + 1/3, toward 1.0) is applied to both routes and
both the raw and adjusted figures are kept. It originates as an empirical
correction for *estimated* betas, so its application to a peer median is the
weaker of the two cases; 4.4 states it as a qualification of the policy as a
whole rather than of the regression route alone, and keeping both figures
means the choice is visible rather than baked in.
"""
from dataclasses import dataclass
from decimal import Decimal

from src.valuation.money import D, divide

#: Framework 4.4 default: peer-median unlevered, relevered to target structure.
BASIS_PEER_RELEVERED = "peer_median_relevered"
#: Permitted only for a large, liquid, long-listed name genuinely lacking a
#: comp set, or where the thesis is that its risk profile differs from peers.
BASIS_REGRESSION = "regression"

BETA_BASES = (BASIS_PEER_RELEVERED, BASIS_REGRESSION)

_BLUME_WEIGHT = divide(D(2), D(3))
_BLUME_ANCHOR = divide(D(1), D(3))


class BetaError(ValueError):
    """Beta cannot be resolved from the inputs given."""


@dataclass(frozen=True)
class Peer:
    """A comparable, with what is needed to strip its capital structure out."""

    ticker: str
    levered_beta: Decimal
    debt_to_equity: Decimal
    tax_rate: Decimal

    @property
    def unlevered_beta(self) -> Decimal:
        return unlever(self.levered_beta, self.debt_to_equity, self.tax_rate)


def unlever(levered: Decimal, debt_to_equity: Decimal,
            tax_rate: Decimal) -> Decimal:
    """Hamada: strip capital structure out, leaving business risk.

    beta_u = beta_l / (1 + (1 - t) x D/E)
    """
    return divide(levered, Decimal(1) + (Decimal(1) - tax_rate) * debt_to_equity)


def relever(unlevered: Decimal, debt_to_equity: Decimal,
            tax_rate: Decimal) -> Decimal:
    """Hamada, the other way: put the target structure back on."""
    return unlevered * (Decimal(1) + (Decimal(1) - tax_rate) * debt_to_equity)


def blume(beta: Decimal) -> Decimal:
    """2/3 x beta + 1/3, toward 1.0. Betas mean-revert (4.4)."""
    return _BLUME_WEIGHT * beta + _BLUME_ANCHOR


def median(values: list[Decimal]) -> Decimal:
    """Median in Decimal. Even counts average the two middle values."""
    if not values:
        raise BetaError("no values to take a median of")
    ordered = sorted(values)
    midpoint = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[midpoint]
    return divide(ordered[midpoint - 1] + ordered[midpoint], D(2))


@dataclass(frozen=True)
class BetaPolicy:
    """Both betas, the one adopted, and the spread between them."""

    peers: tuple[Peer, ...]
    peer_median_unlevered: Decimal | None
    peer_relevered: Decimal | None
    peer_relevered_adjusted: Decimal | None
    regression: Decimal | None
    regression_adjusted: Decimal | None
    basis: str
    reason: str

    @property
    def beta(self) -> Decimal:
        """The beta the WACC uses."""
        chosen = (self.regression_adjusted if self.basis == BASIS_REGRESSION
                  else self.peer_relevered_adjusted)
        if chosen is None:
            raise BetaError(f"basis {self.basis!r} has no computed beta")
        return chosen

    @property
    def spread(self) -> Decimal | None:
        """Regression minus peer-relevered, both Blume-adjusted.

        None when only one route was computable -- a recent IPO has no
        regression beta at all, and reporting a spread of zero there would
        assert an agreement that was never tested.
        """
        if self.regression_adjusted is None or self.peer_relevered_adjusted is None:
            return None
        return self.regression_adjusted - self.peer_relevered_adjusted

    def render(self) -> str:
        def show(value: Decimal | None) -> str:
            return "n/a" if value is None else f"{value.quantize(Decimal('0.0001'))}"

        spread = self.spread
        line = (f"Beta {show(self.beta)} ({self.basis}; {self.reason})  "
                f"peer-relevered {show(self.peer_relevered_adjusted)}  "
                f"regression {show(self.regression_adjusted)}")
        if spread is None:
            return line + "  spread n/a — only one route computable"
        return line + f"  spread {show(spread)}"


def beta_policy(peers: tuple[Peer, ...] = (),
                regression: Decimal | None = None,
                target_debt_to_equity: Decimal | None = None,
                tax_rate: Decimal | None = None,
                basis: str = BASIS_PEER_RELEVERED,
                reason: str = "framework 4.4 default") -> BetaPolicy:
    """Compute both routes, adopt one, and keep the spread visible."""
    if basis not in BETA_BASES:
        raise BetaError(f"unknown beta basis {basis!r}; legal are {BETA_BASES}")

    peer_median_unlevered = peer_relevered = peer_adjusted = None
    if peers:
        if target_debt_to_equity is None or tax_rate is None:
            raise BetaError(
                "relevering peers needs a target debt/equity and a tax rate")
        peer_median_unlevered = median([p.unlevered_beta for p in peers])
        peer_relevered = relever(peer_median_unlevered, target_debt_to_equity,
                                 tax_rate)
        peer_adjusted = blume(peer_relevered)

    regression_adjusted = None if regression is None else blume(regression)

    if basis == BASIS_PEER_RELEVERED and peer_adjusted is None:
        raise BetaError(
            "no peers supplied, so the framework 4.4 default (peer-median "
            "unlevered, relevered) cannot be computed. Supply peers, or state "
            "a reason for preferring the regression beta.")
    if basis == BASIS_REGRESSION and regression_adjusted is None:
        raise BetaError("basis is regression, but no regression beta was given")

    return BetaPolicy(
        peers=peers, peer_median_unlevered=peer_median_unlevered,
        peer_relevered=peer_relevered, peer_relevered_adjusted=peer_adjusted,
        regression=regression, regression_adjusted=regression_adjusted,
        basis=basis, reason=reason)
