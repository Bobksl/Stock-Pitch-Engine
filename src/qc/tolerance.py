"""P1.2 — how close is close enough, derived from how the figure is written.

There is no configurable tolerance and no global epsilon. A claim's precision is
a statement the author made: "$245.1 billion" asserts the figure rounds to
245.1 at one decimal place, and nothing more. So the admissible interval is one
half-ulp of the last written digit, and the rule falls straight out:

    resolves  iff  |fact - claim| <= ulp/2

The two cases the spec names, against MSFT-style revenue of 245,122,000,000:

    "$245.1 billion"  claim 245_100_000_000  half-ulp 50_000_000
                      |diff| =  22,000,000   <= 50,000,000   resolves
    "$245.9 billion"  claim 245_900_000_000  half-ulp 50_000_000
                      |diff| = 778,000,000   >  50,000,000   fails

The interval is CLOSED at both ends on purpose. A value landing exactly on the
boundary is a rounding tie, and half-up and half-even disagree there; failing a
draft over a tie-breaking convention would be noise, not a finding.

Everything is Decimal. A float epsilon would make the boundary itself
approximate, which is an absurd way to run an exactness check.
"""
from dataclasses import dataclass
from decimal import Decimal

from src.qc.claims import NumericClaim


def fmt(value: Decimal) -> str:
    """Plain fixed-point with thousands separators.

    Decimal keeps its exponent, so `Decimal("1e9")` formats as "1E+9" under
    the default spec -- unreadable in a failure message about a scale error,
    which is precisely where these strings get read.
    """
    return f"{value:,f}"


@dataclass(frozen=True)
class Tolerance:
    """The interval a claim admits, and why it is that wide."""

    claim: Decimal
    half_ulp: Decimal

    @property
    def low(self) -> Decimal:
        return self.claim - self.half_ulp

    @property
    def high(self) -> Decimal:
        return self.claim + self.half_ulp

    def accepts(self, actual: Decimal) -> bool:
        return self.low <= actual <= self.high

    def error(self, actual: Decimal) -> Decimal:
        """How far outside the interval `actual` sits; 0 when it is inside."""
        if self.accepts(actual):
            return Decimal(0)
        return actual - self.high if actual > self.high else self.low - actual

    def __str__(self) -> str:
        return f"[{fmt(self.low)} .. {fmt(self.high)}]"


def tolerance_of(claim: NumericClaim) -> Tolerance:
    """The admissible interval for a claim, from its written precision alone."""
    return Tolerance(claim=claim.value, half_ulp=abs(claim.ulp) / 2)


def resolves(claim: NumericClaim, actual: Decimal) -> bool:
    return tolerance_of(claim).accepts(actual)


def scale_hypothesis(claim: NumericClaim, actual: Decimal) -> Decimal | None:
    """The scale that WOULD have made this claim resolve, if there is one.

    Reported only in failure messages. It is a hint about how to fix a draft --
    "you wrote 137,791 in a column with no unit; at millions it matches" -- and
    is never applied: silently adopting the scale that makes a claim true would
    rescue the 1000x error the check exists to catch.
    """
    if claim.scale == 0:
        return None
    for candidate in (Decimal(1), Decimal("1e3"), Decimal("1e6"),
                      Decimal("1e9"), Decimal("1e12")):
        if candidate == claim.scale:
            continue
        exponent = claim.digits.as_tuple().exponent
        probe = Tolerance(claim=claim.digits * candidate,
                          half_ulp=abs(Decimal(1).scaleb(exponent) * candidate) / 2)
        if probe.accepts(actual):
            return candidate
    return None
