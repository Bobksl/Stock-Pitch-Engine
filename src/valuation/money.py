"""P2.2 — the Decimal boundary. Financial arithmetic never touches float.

Framework P1 and the Phase 2 non-negotiables: all arithmetic in Python, in
`Decimal`, never float. The rule is easy to state and easy to violate by
accident, because `Decimal(0.1)` is perfectly legal Python and silently yields
0.1000000000000000055511151231257827021181583404541015625. One such
construction anywhere upstream and the exactness claim of every downstream
test is worthless -- and worse, it is worthless invisibly, which is the exact
failure mode this whole layer exists to catch.

So `D()` refuses a float outright.

There is exactly one sanctioned float crossing, `from_spreadsheet()`, named
after the only place floats legitimately appear: cells read out of a workbook,
where openpyxl has already parsed the file's decimal text into binary64 before
we ever see it. It takes the shortest round-tripping decimal representation
(`repr`), which recovers the literal the modeller typed -- "1.22" -- rather
than the binary expansion of it. Anywhere else, a float is a bug.

Precision is 50 significant digits. Excel computes in binary64, roughly 15-17
significant digits, so we are strictly more precise than the artifact we
reconcile against in C11, and our own rounding can never be the explanation
for a divergence at the 1e-9 relative tolerance that test uses.
"""
from decimal import Decimal, ROUND_HALF_UP, localcontext
from typing import Any

#: Significant digits for every valuation computation. See module docstring.
PRECISION = 50

#: Published share prices are quoted to the cent. Reproduction of a target
#: price is asserted at this quantum, not bit-for-bit: Excel's binary64 and a
#: 50-digit Decimal agree to ~15 significant figures, which is many orders
#: tighter than a price rounded to two places.
PRICE_QUANTUM = Decimal("0.01")


class PrecisionError(TypeError):
    """A float reached financial arithmetic without passing the boundary."""


def D(value: Any) -> Decimal:
    """Construct a Decimal, refusing float.

    `str` and `int` are exact; `Decimal` passes through. A float is rejected
    with the reason, because the fix is always the same and always local:
    quote the literal, or route it through `from_spreadsheet` if it genuinely
    came out of a workbook cell.
    """
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        raise PrecisionError(f"bool {value!r} is not a financial quantity")
    if isinstance(value, float):
        raise PrecisionError(
            f"float {value!r} cannot become a financial figure directly: it is "
            f"already a binary approximation ({Decimal(value)}). Quote the "
            f"literal as a string, or use from_spreadsheet() if it was read "
            f"from a workbook cell.")
    if isinstance(value, (int, str)):
        return Decimal(value)
    raise PrecisionError(f"cannot make a Decimal from {type(value).__name__}")


def from_spreadsheet(value: Any) -> Decimal:
    """The one sanctioned float -> Decimal crossing: a workbook cell.

    openpyxl hands back binary64 because that is what the file stores. `repr`
    of a Python float is the shortest string that round-trips, so it recovers
    the decimal literal the modeller typed rather than its binary expansion:
    `repr(1.22)` is "1.22", not "1.2199999999999999733546474089962430298328399658203125".
    """
    if isinstance(value, bool):
        raise PrecisionError(f"cell holds a bool ({value!r}), not a number")
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            raise PrecisionError(f"cell holds a non-finite value ({value!r})")
        return Decimal(repr(value))
    if isinstance(value, str):
        return Decimal(value)
    raise PrecisionError(f"cell holds {type(value).__name__}, not a number")


def power(base: Decimal, exponent: Decimal) -> Decimal:
    """`base ** exponent` at full precision, fractional exponents included.

    Decimal supports non-integer exponents via correctly-rounded exp/ln at the
    context precision, which is how the stub and mid-year discount factors of
    a DCF -- (1+WACC)^(31/6) and friends -- stay exact enough to reconcile
    against a spreadsheet without ever touching float.
    """
    with localcontext() as ctx:
        ctx.prec = PRECISION
        return base ** exponent


def divide(numerator: Decimal, denominator: Decimal) -> Decimal:
    """Division at full precision, with a named error on a zero denominator.

    A bare DivisionByZero from inside a WACC-minus-g denominator is a
    genuinely confusing traceback; the interesting fact is that the spread
    collapsed, and the message should say so.
    """
    if denominator == 0:
        raise ZeroDivisionError("denominator is zero")
    with localcontext() as ctx:
        ctx.prec = PRECISION
        return numerator / denominator


def quantize_price(value: Decimal) -> Decimal:
    """Round to the quoted cent, half-up as published prices are."""
    return value.quantize(PRICE_QUANTUM, rounding=ROUND_HALF_UP)


def as_percent(value: Decimal, places: str = "0.01") -> Decimal:
    """A rate expressed in percentage points, for reports and thresholds."""
    with localcontext() as ctx:
        ctx.prec = PRECISION
        return (value * 100).quantize(Decimal(places), rounding=ROUND_HALF_UP)
