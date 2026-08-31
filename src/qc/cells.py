"""P1.2 — model cells: derived figures, recomputed rather than trusted.

A pitch is full of numbers that are not facts-table rows: margins, growth rates,
multiples, per-share amounts. Framework 6.4 resolves these to "a model cell",
and framework P1 forbids an LLM from producing any of them.

A cell therefore declares an operation and its inputs, and the verifier
**recomputes it** from the cited facts in Decimal before comparing it to the
prose. Storing the value and trusting it would leave the obvious hole: a wrong
margin, faithfully recorded, would verify clean.

The operation vocabulary is closed and there is no expression language and no
eval. A formula the map cannot express is a reviewable addition to this file,
which is the same discipline concept_map.yaml applies to tag resolution -- and
for the same reason: how a number is produced must be visible in a diff.

Phase 2 builds the valuation engine on this contract; Phase 1 needs only enough
of it to check the derived figures a Section 1 draft actually contains.

Declaration (a YAML block in the draft, or a sidecar file):

    ic_margin_fy26:
      op: ratio
      inputs:
        - {cik: 789019, concept: operating_income, period_end: 2026-06-30,
           segments: {us-gaap:StatementBusinessSegmentsAxis: msft:IntelligentCloudMember}}
        - {cik: 789019, concept: revenue, period_end: 2026-06-30,
           segments: {us-gaap:StatementBusinessSegmentsAxis: msft:IntelligentCloudMember}}
      quantize: "0.0001"
      unit: pure
"""
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, DivisionByZero, InvalidOperation
from typing import Any

import yaml

from src.facts.api import Fact, get_fact


class CellError(ValueError):
    """A model cell is undeclared, malformed, cyclic, or uncomputable."""


# --------------------------------------------------------------------------
# The closed operation vocabulary.
#
# Each entry is (arity, function). `None` arity means variadic. Nothing here
# reads a string as code; adding an operation is a reviewable diff.
# --------------------------------------------------------------------------

def _ratio(a: Decimal, b: Decimal) -> Decimal:
    if b == 0:
        raise CellError("ratio: denominator is zero")
    return a / b


def _growth(a: Decimal, b: Decimal) -> Decimal:
    if b == 0:
        raise CellError("growth: base period is zero")
    return a / b - 1


OPS: dict[str, tuple[int | None, Any]] = {
    "sum": (None, lambda *xs: sum(xs, Decimal(0))),
    "difference": (2, lambda a, b: a - b),
    "product": (2, lambda a, b: a * b),
    "ratio": (2, _ratio),
    "growth": (2, _growth),
}


@dataclass(frozen=True)
class CellResult:
    """A recomputed value and the facts it was computed from."""

    name: str
    value: Decimal
    unit: str
    inputs: tuple[Fact, ...] = ()
    op: str = ""

    @property
    def citation(self) -> str:
        """A model cell cites its formula and every fact underneath it."""
        head = f"model:{self.name} = {self.op}(" + ", ".join(
            f.concept for f in self.inputs) + ")"
        return head + "".join(f"\n        <- {f.citation}" for f in self.inputs)


@dataclass
class CellRegistry:
    """Declared model cells, recomputed on demand.

    Results are memoised per registry instance so a cell referenced by several
    figures is not recomputed, and so cycle detection has somewhere to stand.
    """

    declarations: dict[str, dict] = field(default_factory=dict)
    as_of: date | None = None
    _cache: dict[str, CellResult] = field(default_factory=dict, repr=False)
    _computing: set[str] = field(default_factory=set, repr=False)

    @classmethod
    def from_yaml(cls, text: str, *, as_of: date | None = None) -> "CellRegistry":
        loaded = yaml.safe_load(text) or {}
        if not isinstance(loaded, dict):
            raise CellError("model cell declarations must be a mapping")
        return cls(declarations=loaded, as_of=as_of)

    def __contains__(self, name: str) -> bool:
        return name in self.declarations

    # ----------------------------------------------------------------------

    def compute(self, name: str) -> CellResult:
        if name in self._cache:
            return self._cache[name]
        if name in self._computing:
            raise CellError(f"model cell {name!r} is defined in terms of itself")
        if name not in self.declarations:
            raise CellError(f"model cell {name!r} is not declared")

        decl = self.declarations[name]
        if not isinstance(decl, dict) or "op" not in decl:
            raise CellError(f"model cell {name!r}: an 'op' is required")
        op_name = decl["op"]
        if op_name not in OPS:
            raise CellError(
                f"model cell {name!r}: unknown op {op_name!r}; "
                f"the vocabulary is {sorted(OPS)}")

        arity, fn = OPS[op_name]
        raw_inputs = decl.get("inputs") or []
        if not isinstance(raw_inputs, list) or not raw_inputs:
            raise CellError(f"model cell {name!r}: 'inputs' must be a non-empty list")
        if arity is not None and len(raw_inputs) != arity:
            raise CellError(
                f"model cell {name!r}: {op_name} takes {arity} inputs, "
                f"got {len(raw_inputs)}")

        self._computing.add(name)
        try:
            values: list[Decimal] = []
            facts: list[Fact] = []
            for ref in raw_inputs:
                value, fact = self._resolve_input(name, ref)
                values.append(value)
                if fact is not None:
                    facts.append(fact)
            try:
                value = fn(*values)
            except (InvalidOperation, DivisionByZero, ZeroDivisionError) as exc:
                raise CellError(f"model cell {name!r}: {op_name} failed: {exc}") from None
        finally:
            self._computing.discard(name)

        if quantum := decl.get("quantize"):
            value = value.quantize(Decimal(str(quantum)))

        result = CellResult(name=name, value=value, unit=decl.get("unit", "pure"),
                            inputs=tuple(facts), op=op_name)
        self._cache[name] = result
        return result

    def _resolve_input(self, owner: str, ref: Any) -> tuple[Decimal, Fact | None]:
        """A cell input is a fact reference, another cell, or a declared literal."""
        if isinstance(ref, dict) and "cell" in ref:
            return self.compute(ref["cell"]).value, None
        if isinstance(ref, dict) and "literal" in ref:
            # Allowed, but it must say where it came from: an undocumented
            # constant in a valuation is exactly what P3 exists to prevent.
            if not ref.get("note"):
                raise CellError(
                    f"model cell {owner!r}: a literal input requires a 'note' "
                    f"saying where the number comes from")
            return Decimal(str(ref["literal"])), None
        if isinstance(ref, dict) and {"cik", "concept", "period_end"} <= set(ref):
            period_end = ref["period_end"]
            if isinstance(period_end, str):
                period_end = date.fromisoformat(period_end)
            fact = get_fact(int(ref["cik"]), ref["concept"], period_end,
                            segments=ref.get("segments") or {}, as_of=self.as_of)
            if fact is None:
                raise CellError(
                    f"model cell {owner!r}: no fact for {ref['concept']} "
                    f"cik={ref['cik']} period_end={period_end} "
                    f"segments={ref.get('segments') or {}}")
            return fact.value, fact
        raise CellError(
            f"model cell {owner!r}: an input must be a fact reference "
            f"(cik/concept/period_end), {{cell: name}}, or {{literal, note}}")
