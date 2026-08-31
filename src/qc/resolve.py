"""P1.2 — does the cited source actually say what the prose says?

One claim in, one Resolution out. There is exactly one passing status; every
other outcome blocks publication. There are no severities and no allowlist --
that was a decision, not an omission -- but there are distinct FAILURE REASONS,
because "no provenance" and "cited row disagrees" need different fixes and a
gate that cannot tell you which one you have is a gate you will learn to ignore.

Order of checks per claim, first failure wins:

    1. scale declared?          an unlabelled magnitude is not checkable
    2. anchor present?          framework 6.4: no free-floating figures
    3. anchor in the index?
    4. source exists?           fact row / model cell / external record
    5. unit compatible?         "$4.2" against a share count is not a match
    6. inside the tolerance?    the half-ulp rule (tolerance.py)
"""
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from src.facts.api import get_fact
from src.qc.anchors import KIND_EXT, KIND_FACT, KIND_MODEL, Anchor
from src.qc.cells import CellError, CellRegistry
from src.qc.claims import (
    KIND_BARE,
    KIND_CURRENCY,
    KIND_MULTIPLE,
    KIND_PERCENT,
    KIND_SHARES,
    NumericClaim,
)
from src.qc.external import ExternalRecord
from src.qc.tolerance import fmt, scale_hypothesis, tolerance_of

RESOLVED = "resolved"
MISMATCH = "mismatch"
UNANCHORED = "unanchored"
UNKNOWN_ANCHOR = "unknown_anchor"
MISSING_SOURCE = "missing_source"
UNIT_MISMATCH = "unit_mismatch"
SCALE_UNDECLARED = "scale_undeclared"

#: Every status except RESOLVED blocks publication.
FAILURE_STATUSES = (MISMATCH, UNANCHORED, UNKNOWN_ANCHOR, MISSING_SOURCE,
                    UNIT_MISMATCH, SCALE_UNDECLARED)


@dataclass(frozen=True)
class Resolution:
    """The verdict on one figure, with everything needed to act on it."""

    claim: NumericClaim
    status: str
    detail: str
    actual: Decimal | None = None
    citation: str | None = None

    @property
    def ok(self) -> bool:
        return self.status == RESOLVED

    def render(self) -> str:
        head = (f"line {self.claim.line}, col {self.claim.span[0]}: "
                f"{self.claim.text!r} — {self.status}")
        return f"{head}\n    {self.detail}" + (
            f"\n    source: {self.citation}" if self.citation else "")


def _unit_compatible(claim: NumericClaim, unit: str | None) -> bool:
    """Does the source's unit match the way the figure is written?

    A bare, undecorated numeral asserts no unit, so nothing to contradict; the
    value comparison carries it alone.
    """
    if unit is None or claim.kind == KIND_BARE:
        return True
    if claim.kind == KIND_CURRENCY:
        # A per-share amount ("$3.20" of EPS) is stored as USD/shares.
        return unit in (claim.unit, f"{claim.unit}/shares")
    if claim.kind == KIND_SHARES:
        return unit == "shares"
    if claim.kind in (KIND_PERCENT, KIND_MULTIPLE):
        return unit in ("pure", "ratio", "percent")
    return True


def _fail(claim: NumericClaim, status: str, detail: str,
          actual: Decimal | None = None, citation: str | None = None) -> Resolution:
    return Resolution(claim=claim, status=status, detail=detail,
                      actual=actual, citation=citation)


def _lookup(claim: NumericClaim, anchor: Anchor, *, cells: CellRegistry | None,
            externals: dict[str, ExternalRecord],
            as_of: date | None) -> Resolution | tuple[Decimal, str | None, str]:
    """(value, unit, citation) from the anchor's source, or a failing Resolution."""
    if anchor.kind == KIND_FACT:
        fact = get_fact(anchor.cik, anchor.concept, anchor.period_end,
                        segments=anchor.segments, as_of=as_of)
        if fact is None:
            return _fail(claim, MISSING_SOURCE,
                         f"the citation index points at a fact that does not exist: "
                         f"{anchor.describe()}")
        return fact.value, fact.unit, fact.citation

    if anchor.kind == KIND_MODEL:
        name = anchor.body.get("cell")
        if cells is None or name not in cells:
            return _fail(claim, MISSING_SOURCE,
                         f"model cell {name!r} is cited but not declared")
        try:
            result = cells.compute(name)
        except CellError as exc:
            return _fail(claim, MISSING_SOURCE, f"model cell {name!r}: {exc}")
        return result.value, result.unit, result.citation

    key = anchor.body.get("record")
    record = externals.get(key)
    if record is None:
        return _fail(claim, MISSING_SOURCE,
                     f"no external record named {key!r} in the external store")
    return record.value, record.unit, record.citation


def resolve_claim(claim: NumericClaim, index: dict[str, Anchor], *,
                  cells: CellRegistry | None = None,
                  externals: dict[str, ExternalRecord] | None = None,
                  as_of: date | None = None) -> Resolution:
    """Verify one figure against the source it cites."""
    externals = externals or {}

    if not claim.scale_declared:
        return _fail(claim, SCALE_UNDECLARED,
                     f"the column {claim.column!r} declares no unit, so this figure "
                     f"has no determinable scale. Put the unit in the header "
                     f"(e.g. 'Revenue ($m)') or write it on the figure.")

    if claim.anchor is None:
        return _fail(claim, UNANCHORED,
                     "no citation anchor. Framework 6.4: every figure resolves to a "
                     "facts row, a model cell, or a declared external record.")

    anchor = index.get(claim.anchor)
    if anchor is None:
        return _fail(claim, UNKNOWN_ANCHOR,
                     f"anchor [^{claim.anchor}] has no entry in the citation index")

    found = _lookup(claim, anchor, cells=cells, externals=externals, as_of=as_of)
    if isinstance(found, Resolution):
        return found
    actual, unit, citation = found

    if not _unit_compatible(claim, unit):
        return _fail(claim, UNIT_MISMATCH,
                     f"the figure is written as {claim.kind} but the cited source "
                     f"is in {unit!r}", actual=actual, citation=citation)

    tol = tolerance_of(claim)
    if tol.accepts(actual):
        return Resolution(claim=claim, status=RESOLVED,
                          detail=f"{fmt(actual)} is within {tol}",
                          actual=actual, citation=citation)

    detail = (f"the cited source says {fmt(actual)}; the draft says "
              f"{fmt(claim.value)}, which admits {tol}. "
              f"Off by {fmt(tol.error(actual))}.")
    if (hypothesis := scale_hypothesis(claim, actual)) is not None:
        detail += (f" It would resolve if the figure were read at scale "
                   f"{fmt(hypothesis)} rather than {fmt(claim.scale)} — declare "
                   f"the intended unit rather than relying on that.")
    return _fail(claim, MISMATCH, detail, actual=actual, citation=citation)
