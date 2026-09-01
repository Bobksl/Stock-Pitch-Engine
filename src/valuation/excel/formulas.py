"""P2.5 — the paired operation vocabulary: one Python function, one formula.

Framework 4.12 makes the workbook a two-way interface with live formulas, and
Python keeps a parallel calculation so nothing depends on Excel being
installed. The obvious hazard is that the two drift: a change made to one and
not the other produces a workbook that disagrees with the report built from
the same inputs, silently, in a direction nobody checks.

C11 catches that end to end, but an end-to-end failure only says "the target
price disagrees" and leaves the search to a human. So every operation is
declared once, here, with both of its implementations side by side, and a test
recalculates each one in isolation. A pairing bug then names the operation
that broke instead of the workbook that noticed.

The vocabulary is closed and deliberately echoes `qc/cells.py`, which resolves
derived figures through its own closed set for the same reason: how a number
is produced must be visible in a diff. The five names shared with that module
(sum, difference, product, ratio, growth) mean the same thing here.
"""
from dataclasses import dataclass
from decimal import Decimal
from typing import Callable

from src.valuation.money import D, divide, power


@dataclass(frozen=True)
class Op:
    """One operation, in both languages."""

    name: str
    arity: int | None                   # None means variadic
    python: Callable[..., Decimal]
    excel: Callable[..., str]           # cell references in, formula body out


def _perpetuity(final_flow: Decimal, growth: Decimal, rate: Decimal) -> Decimal:
    return divide(final_flow * (Decimal(1) + growth), rate - growth)


OPS: dict[str, Op] = {op.name: op for op in (
    Op("sum", None,
       lambda *xs: sum(xs, D(0)),
       lambda *refs: "+".join(refs)),
    Op("difference", 2,
       lambda a, b: a - b,
       lambda a, b: f"{a}-{b}"),
    Op("product", 2,
       lambda a, b: a * b,
       lambda a, b: f"{a}*{b}"),
    Op("ratio", 2,
       divide,
       lambda a, b: f"{a}/{b}"),
    Op("growth", 2,
       lambda a, b: divide(a, b) - Decimal(1),
       lambda a, b: f"{a}/{b}-1"),
    Op("grow_by", 2,
       lambda base, rate: base * (Decimal(1) + rate),
       lambda base, rate: f"{base}*(1+{rate})"),
    Op("complement", 1,
       lambda x: Decimal(1) - x,
       lambda x: f"1-{x}"),
    Op("negated_product", 2,
       lambda a, b: -(a * b),
       lambda a, b: f"-{a}*{b}"),
    Op("weighted_pair", 4,
       lambda a, wa, b, wb: a * wa + b * wb,
       lambda a, wa, b, wb: f"{a}*{wa}+{b}*{wb}"),
    Op("discount_factor", 2,
       lambda rate, exponent: divide(Decimal(1),
                                     power(Decimal(1) + rate, exponent)),
       lambda rate, exponent: f"1/POWER(1+{rate},{exponent})"),
    Op("perpetuity", 3,
       _perpetuity,
       lambda flow, growth, rate: f"{flow}*(1+{growth})/({rate}-{growth})"),
    Op("minimum", None,
       lambda *xs: min(xs),
       lambda *refs: "MIN(" + ",".join(refs) + ")"),
    Op("maximum", None,
       lambda *xs: max(xs),
       lambda *refs: "MAX(" + ",".join(refs) + ")"),
    Op("per_point", 2,
       lambda value, rate: divide(value, rate * Decimal(100)),
       lambda value, rate: f"{value}/({rate}*100)"),
    Op("times_points", 2,
       lambda value, rate: value * rate * Decimal(100),
       lambda value, rate: f"{value}*{rate}*100"),
    Op("upside", 2,
       lambda implied, current: divide(implied, current) - Decimal(1),
       lambda implied, current: f"{implied}/{current}-1"),
    # The framework 4.9 price bridge in one step. Kept as a single operation
    # rather than composed from product/sum/ratio because the decomposition
    # evaluates it four times at different arguments, and four hand-built
    # nestings are four chances to transpose a reference.
    Op("implied_price", 5,
       lambda multiple, metric, cash, debt, shares: divide(
           multiple * metric + cash - debt, shares),
       lambda multiple, metric, cash, debt, shares:
           f"({multiple}*{metric}+{cash}-{debt})/{shares}"),
)}


class FormulaError(ValueError):
    """An operation was used with the wrong number of arguments."""


def _check(name: str, count: int) -> Op:
    try:
        op = OPS[name]
    except KeyError:
        raise FormulaError(
            f"no operation {name!r}. Adding one is a reviewable change to "
            f"src/valuation/excel/formulas.py, and it must arrive with both "
            f"implementations.") from None
    if op.arity is not None and count != op.arity:
        raise FormulaError(f"{name} takes {op.arity} arguments, got {count}")
    return op


def formula(name: str, *refs: str) -> str:
    """The Excel formula for an operation over the given cell references."""
    return "=" + _check(name, len(refs)).excel(*refs)


def compute(name: str, *values: Decimal) -> Decimal:
    """The Python result of the same operation over the given values."""
    return _check(name, len(values)).python(*values)


def sum_range(first: str, last: str) -> str:
    """`=SUM(first:last)`. A range has no per-argument Python counterpart;
    the paired operation is `sum` over the same cells."""
    return f"=SUM({first}:{last})"


def min_range(first: str, last: str) -> str:
    """`=MIN(first:last)`; the paired operation is `minimum`."""
    return f"=MIN({first}:{last})"


def max_range(first: str, last: str) -> str:
    """`=MAX(first:last)`; the paired operation is `maximum`."""
    return f"=MAX({first}:{last})"
