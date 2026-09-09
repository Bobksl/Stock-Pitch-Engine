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
from src.qc.external import ExternalRecord


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


# --------------------------------------------------------------------------
# The SERIES operation vocabulary (spec 6.4, v1.5).
#
# 2.4's peer drawdown analysis is the first thing in the framework that is not
# arithmetic over two scalars, and all three existing routes fail it. Prices
# are not in XBRL, so these cannot be facts. A drawdown is not expressible in
# the vocabulary above, so they could not be model cells as it stood. And
# storing a computed statistic in an external record would RECORD it rather
# than recompute it -- a wrong drawdown recorded faithfully would verify clean,
# which is the hole 6.4 exists to close.
#
# So a second closed vocabulary, kept separate from the first rather than
# merged into it: a caller reading OPS still sees only arithmetic, and a
# `ratio` over two price series -- a type confusion that happens to produce a
# number -- is refused rather than computed.
#
# The measurement window lives in the input declaration (`from` / `to`), so a
# statistic states the period it was measured over instead of implying it, and
# every op below is a pure function of the slices it is handed.
# --------------------------------------------------------------------------

def _series_max_drawdown(series):
    from src.pitch.drawdown import max_drawdown
    return max_drawdown(series)[0]


def _series_recovery_days(series):
    from src.pitch.drawdown import max_drawdown, recovery_date
    _, peak, trough = max_drawdown(series)
    recovered = recovery_date(series, peak, trough)
    if recovered is None:
        raise CellError(
            "the drawdown is not recovered within this window, so there is no "
            "recovery time to cite. Reporting zero would invert the reading")
    return Decimal((recovered - trough).days)


def _series_downside_capture(peer, benchmark):
    from src.pitch.drawdown import DrawdownError, downside_capture
    try:
        return downside_capture(peer[-1][1] / peer[0][1] - 1,
                                benchmark[-1][1] / benchmark[0][1] - 1)
    except DrawdownError as exc:
        raise CellError(str(exc)) from None


def _series_correlation(peer, benchmark):
    from src.pitch.drawdown import DrawdownError, correlation
    try:
        return correlation(peer, benchmark)
    except DrawdownError as exc:
        raise CellError(str(exc)) from None


def _series_beta(peer, benchmark):
    from src.pitch.drawdown import DrawdownError, stress_beta
    try:
        return stress_beta(peer, benchmark)
    except DrawdownError as exc:
        raise CellError(str(exc)) from None


SERIES_OPS: dict[str, tuple[int, Any]] = {
    "max_drawdown": (1, _series_max_drawdown),
    "recovery_days": (1, _series_recovery_days),
    "downside_capture": (2, _series_downside_capture),
    "correlation": (2, _series_correlation),
    "stress_beta": (2, _series_beta),
}


@dataclass(frozen=True)
class CellResult:
    """A recomputed value and the facts it was computed from."""

    name: str
    value: Decimal
    unit: str
    inputs: tuple[Fact, ...] = ()
    op: str = ""
    #: Citations for series inputs, which are not Facts: one line per declared
    #: series, naming the instrument, its window and where the prices came from.
    series: tuple[str, ...] = ()

    @property
    def citation(self) -> str:
        """A model cell cites its formula and everything underneath it."""
        parts = [f.concept for f in self.inputs] + list(self.series)
        head = f"model:{self.name} = {self.op}(" + ", ".join(parts) + ")"
        return (head
                + "".join(f"\n        <- {f.citation}" for f in self.inputs)
                + "".join(f"\n        <- prices:{s}" for s in self.series))


@dataclass
class CellRegistry:
    """Declared model cells, recomputed on demand.

    Results are memoised per registry instance so a cell referenced by several
    figures is not recomputed, and so cycle detection has somewhere to stand.
    """

    declarations: dict[str, dict] = field(default_factory=dict)
    as_of: date | None = None
    externals: dict[str, ExternalRecord] = field(default_factory=dict)
    _cache: dict[str, CellResult] = field(default_factory=dict, repr=False)
    _computing: set[str] = field(default_factory=set, repr=False)

    @classmethod
    def from_yaml(cls, text: str, *, as_of: date | None = None,
                  externals: dict[str, ExternalRecord] | None = None) -> "CellRegistry":
        loaded = yaml.safe_load(text) or {}
        if not isinstance(loaded, dict):
            raise CellError("model cell declarations must be a mapping")
        return cls(declarations=loaded, as_of=as_of, externals=externals or {})

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
        if op_name not in OPS and op_name not in SERIES_OPS:
            raise CellError(
                f"model cell {name!r}: unknown op {op_name!r}; the "
                f"vocabularies are {sorted(OPS)} over scalars and "
                f"{sorted(SERIES_OPS)} over series")

        if op_name in SERIES_OPS:
            return self._compute_series(name, decl, op_name)

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

    def _compute_series(self, name: str, decl: dict, op_name: str) -> CellResult:
        """A series-valued derived figure (6.4, v1.5).

        Kept on its own path rather than folded into the scalar one: the input
        form differs, the arity check differs, and mixing them would let a
        `ratio` over two price series through as a type confusion that happens
        to produce a number.
        """
        arity, fn = SERIES_OPS[op_name]
        refs = decl.get("inputs") or []
        if not isinstance(refs, list) or len(refs) != arity:
            raise CellError(
                f"model cell {name!r}: {op_name} takes {arity} series input(s), "
                f"got {len(refs) if isinstance(refs, list) else refs!r}")

        series_args, citations = [], []
        for ref in refs:
            if not isinstance(ref, dict) or "series" not in ref:
                raise CellError(
                    f"model cell {name!r}: {op_name} needs a series input "
                    f"{{series, from, to}}, got {ref!r}")
            series_args.append(self._resolve_series(name, ref))
            citations.append(_series_citation(ref))

        try:
            value = fn(*series_args)
        except CellError:
            raise
        except (InvalidOperation, DivisionByZero, ZeroDivisionError) as exc:
            raise CellError(f"model cell {name!r}: {op_name} failed: {exc}") from None

        if quantum := decl.get("quantize"):
            value = value.quantize(Decimal(str(quantum)))

        result = CellResult(name=name, value=value, unit=decl.get("unit", "pure"),
                            op=op_name, series=tuple(citations))
        self._cache[name] = result
        return result

    def _resolve_series(self, owner: str, ref: dict) -> list:
        """A declared price window, read from the local prices table.

        The window is part of the DECLARATION, so a statistic states the period
        it was measured over rather than implying it, and two cells over
        different windows are visibly different cells.
        """
        from src.ingest.prices import get_closes

        for field_name in ("from", "to"):
            if ref.get(field_name) is None:
                raise CellError(
                    f"model cell {owner!r}: a series input needs {field_name!r}; "
                    f"a statistic without its window states nothing")
        start, end = _as_date(ref["from"]), _as_date(ref["to"])
        rows = get_closes(ref["series"], start, end)
        if not rows:
            raise CellError(
                f"model cell {owner!r}: no prices for {ref['series']} between "
                f"{start} and {end}")
        return rows

    def _resolve_input(self, owner: str, ref: Any) -> tuple[Decimal, Fact | None]:
        """A cell input is a fact reference, another cell, or a declared literal."""
        if isinstance(ref, dict) and "cell" in ref:
            return self.compute(ref["cell"]).value, None
        if isinstance(ref, dict) and "external" in ref:
            # A multiple is price over earnings: one side is market data with no
            # facts row by construction, the other is XBRL. Both are cited.
            record = self.externals.get(ref["external"])
            if record is None:
                raise CellError(
                    f"model cell {owner!r}: no external record named "
                    f"{ref['external']!r} in the external store")
            return record.value, None
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
        if isinstance(ref, dict) and "series" in ref:
            raise CellError(
                f"model cell {owner!r}: a series input is only legal for the "
                f"series ops {sorted(SERIES_OPS)}; a scalar op over a price "
                f"series is a type confusion that happens to produce a number")
        raise CellError(
            f"model cell {owner!r}: an input must be a fact reference "
            f"(cik/concept/period_end), {{cell: name}}, {{external: key}}, "
            f"or {{literal, note}}")


def _as_date(value: Any) -> date:
    return date.fromisoformat(value) if isinstance(value, str) else value


def _series_citation(ref: dict) -> str:
    """What a series input cites: instrument, window, and where it came from."""
    return (f"{ref['series']} {_as_date(ref['from'])}..{_as_date(ref['to'])}"
            f" | {ref.get('source', 'moomoo')}"
            f" | {ref.get('adjustment', 'forward')}-adjusted")
