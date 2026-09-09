"""P3.2 — framework 7: the sector KPI taxonomy, and its instantiation as cells.

Section 7 fixes a KPI list per sub-group, each entry carrying a name, a
definition, a source (an XBRL tag or filing text), and disclosed-versus-derived.
The list lives in `config/kpi_taxonomy.yaml` rather than here, for the reason
`concept_map.yaml` is data: how a number is produced must be visible in a diff,
and a KPI list is exactly the kind of thing that otherwise accretes silently.

A derived KPI is a model cell
-----------------------------
`declarations_for` turns a sub-group into declarations `CellRegistry` consumes
directly. Nothing new is invented: the op comes from the closed vocabulary in
`cells.py`, the inputs become fact references, and the value is **recomputed at
verification time from cited facts** rather than stored. Framework 6.4 already
covers this, so the 1.5 KPI snapshot inherits the whole provenance layer for
free -- and a KPI the LLM narrates is a figure the LLM did not produce.

Three input forms, and the third is the interesting one
-------------------------------------------------------
`{concept: X}` becomes a fact reference at the requested period, and
`{concept: X, periods_ago: 1}` at the one before it, which is what the `growth`
op needs. `{kpi: Y}` resolves against the same sub-group: to `{cell: Y}` when Y
is derived, and inlined to Y's own fact reference when Y is disclosed in XBRL.

When Y is disclosed in *prose*, it has no facts row by construction, and the
KPI cannot be computed until a `filing_text_disclosure` record (spec 6.4, v1.3)
supplies the figure with a chunk id and a character offset. `declarations_for`
refuses rather than inventing one, and `external_keys` is how the caller says
which record to use. IT services revenue-per-employee is the live case: revenue
is XBRL and headcount is prose, and the KPI is uncomputable until someone reads
the headcount out of the filing and cites where.

Validation happens at load
--------------------------
A derived KPI naming a concept the map does not define, or an op outside the
vocabulary, or the wrong number of inputs for its op, fails when the taxonomy
loads -- not when a pitch is halfway drafted. Same discipline as the rest of
this codebase: refuse early, and name what was asked for.
"""
from dataclasses import dataclass
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from src.config import PROJECT_ROOT
from src.facts.concepts import all_concepts
from src.qc.cells import OPS

TAXONOMY_PATH = PROJECT_ROOT / "config" / "kpi_taxonomy.yaml"

#: The filer states the figure.
DISCLOSED = "disclosed"
#: Computed from disclosed figures, through the closed op vocabulary.
DERIVED = "derived"
DISCLOSURES = (DISCLOSED, DERIVED)

#: A disclosed KPI stated in prose and never tagged. Enters through the
#: `filing_text_disclosure` external record of spec 6.4.
FILING_TEXT = "filing_text"


class KpiError(ValueError):
    """The taxonomy is malformed, or a KPI cannot be instantiated."""


@dataclass(frozen=True)
class Kpi:
    """One entry of the taxonomy. The four fields section 7 requires, typed."""

    name: str
    sub_group: str
    definition: str
    disclosure: str
    #: FILING_TEXT, or {"concept": name}. None for a derived KPI.
    source: Any = None
    #: {"op": ..., "inputs": [...]}. None for a disclosed KPI.
    derivation: dict | None = None
    unit: str = "pure"
    quantize: str | None = None

    @property
    def concept(self) -> str | None:
        """The mapped concept, when this KPI is disclosed in XBRL."""
        return self.source.get("concept") if isinstance(self.source, dict) else None

    @property
    def from_prose(self) -> bool:
        return self.source == FILING_TEXT


@dataclass(frozen=True)
class SubGroup:
    key: str
    label: str
    spec_ref: str
    kpis: tuple[Kpi, ...]

    def __contains__(self, name: str) -> bool:
        return any(k.name == name for k in self.kpis)

    def kpi(self, name: str) -> Kpi:
        for k in self.kpis:
            if k.name == name:
                return k
        raise KpiError(
            f"no KPI {name!r} in sub-group {self.key!r}; it has "
            f"{sorted(k.name for k in self.kpis)}")


# ---------------------------------------------------------------------------
# Loading, with validation
# ---------------------------------------------------------------------------

def _check_inputs(kpi_name: str, group_key: str, op: str, inputs: Any,
                  siblings: set[str]) -> None:
    if not isinstance(inputs, list) or not inputs:
        raise KpiError(f"{group_key}.{kpi_name}: 'inputs' must be a non-empty list")
    arity, _ = OPS[op]
    if arity is not None and len(inputs) != arity:
        raise KpiError(
            f"{group_key}.{kpi_name}: {op} takes {arity} inputs, got {len(inputs)}")

    known = set(all_concepts())
    for ref in inputs:
        if not isinstance(ref, dict):
            raise KpiError(f"{group_key}.{kpi_name}: each input must be a mapping")
        if "concept" in ref:
            if ref["concept"] not in known:
                raise KpiError(
                    f"{group_key}.{kpi_name}: concept {ref['concept']!r} is not in "
                    f"config/concept_map.yaml. Adding it there is a reviewable "
                    f"change; naming it only here forks tag resolution")
        elif "kpi" in ref:
            if ref["kpi"] not in siblings:
                raise KpiError(
                    f"{group_key}.{kpi_name}: input KPI {ref['kpi']!r} is not in "
                    f"the same sub-group")
        elif "literal" in ref:
            if not ref.get("note"):
                raise KpiError(
                    f"{group_key}.{kpi_name}: a literal input requires a 'note' "
                    f"saying where the number comes from")
        else:
            raise KpiError(
                f"{group_key}.{kpi_name}: an input must be {{concept}}, {{kpi}} "
                f"or {{literal, note}}")


def _parse_group(key: str, body: Any) -> SubGroup:
    if not isinstance(body, dict):
        raise KpiError(f"sub-group {key!r}: entry must be a mapping")
    for field in ("label", "spec_ref", "kpis"):
        if not body.get(field):
            raise KpiError(f"sub-group {key!r}: {field!r} is required")

    raw = body["kpis"]
    if not isinstance(raw, dict):
        raise KpiError(f"sub-group {key!r}: 'kpis' must be a mapping")
    siblings = set(raw)

    kpis = []
    for name, entry in raw.items():
        if not isinstance(entry, dict):
            raise KpiError(f"{key}.{name}: entry must be a mapping")
        definition = entry.get("definition")
        if not definition:
            raise KpiError(f"{key}.{name}: section 7 requires a definition")

        disclosure = entry.get("disclosure")
        if disclosure not in DISCLOSURES:
            raise KpiError(
                f"{key}.{name}: disclosure must be one of {DISCLOSURES}, "
                f"got {disclosure!r}")

        source, derivation = entry.get("source"), entry.get("derivation")
        if disclosure == DISCLOSED:
            if source == FILING_TEXT:
                pass
            elif isinstance(source, dict) and "concept" in source:
                if source["concept"] not in set(all_concepts()):
                    raise KpiError(
                        f"{key}.{name}: concept {source['concept']!r} is not in "
                        f"config/concept_map.yaml")
            else:
                raise KpiError(
                    f"{key}.{name}: a disclosed KPI needs source {FILING_TEXT!r} "
                    f"or {{concept: name}}, got {source!r}")
        else:
            if not isinstance(derivation, dict) or "op" not in derivation:
                raise KpiError(f"{key}.{name}: a derived KPI requires derivation.op")
            op = derivation["op"]
            if op not in OPS:
                raise KpiError(
                    f"{key}.{name}: unknown op {op!r}; the closed vocabulary is "
                    f"{sorted(OPS)} and widening it is a change to src/qc/cells.py")
            _check_inputs(name, key, op, derivation.get("inputs"), siblings)

        kpis.append(Kpi(
            name=name, sub_group=key, definition=" ".join(definition.split()),
            disclosure=disclosure, source=source, derivation=derivation,
            unit=entry.get("unit", "pure"),
            quantize=str(entry["quantize"]) if entry.get("quantize") else None))

    return SubGroup(key=key, label=body["label"],
                    spec_ref=str(body["spec_ref"]), kpis=tuple(kpis))


def _parse(loaded: Any) -> dict[str, SubGroup]:
    if not isinstance(loaded, dict) or "sub_groups" not in loaded:
        raise KpiError("the KPI taxonomy must be a mapping with 'sub_groups'")
    return {key: _parse_group(key, body)
            for key, body in loaded["sub_groups"].items()}


@lru_cache(maxsize=4)
def _load_file(path: str) -> tuple[tuple[str, SubGroup], ...]:
    with open(path, encoding="utf-8") as fh:
        return tuple(_parse(yaml.safe_load(fh)).items())


def load_taxonomy(path: str | Path | None = None, *,
                  text: str | None = None) -> dict[str, SubGroup]:
    """The taxonomy, keyed by sub-group. `text` is for tests and refusals."""
    if text is not None:
        return _parse(yaml.safe_load(text))
    return dict(_load_file(str(path or TAXONOMY_PATH)))


def sub_group(key: str) -> SubGroup:
    taxonomy = load_taxonomy()
    if key not in taxonomy:
        raise KpiError(
            f"no KPI sub-group {key!r}; section 7 defines {sorted(taxonomy)}. "
            f"Healthcare and Financials are section 7.5 roadmap, and Financials "
            f"need framework rework rather than a new list")
    return taxonomy[key]


# ---------------------------------------------------------------------------
# Instantiation: a sub-group plus a filer and its periods -> cell declarations
# ---------------------------------------------------------------------------

def _fact_ref(cik: int, concept: str, periods: list[date], back: int,
              segments: dict | None, owner: str) -> dict:
    if back >= len(periods):
        raise KpiError(
            f"{owner}: needs the period {back} back and only {len(periods)} "
            f"were supplied. A growth KPI cannot be computed on one period")
    return {"cik": cik, "concept": concept, "period_end": periods[back],
            "segments": dict(segments or {})}


def declarations_for(group_key: str, cik: int, periods: list[date], *,
                     segments: dict | None = None,
                     external_keys: dict[str, str] | None = None) -> dict[str, dict]:
    """Model-cell declarations for every derived KPI in a sub-group.

    `periods` is newest first. `external_keys` maps a prose-disclosed KPI name
    to the external record supplying it; without one, a derived KPI standing on
    that KPI refuses rather than inventing a figure.
    """
    group = sub_group(group_key)
    if not periods:
        raise KpiError(
            f"{group_key}: no periods supplied, so there is nothing to pin a "
            f"KPI snapshot to")
    keys = external_keys or {}

    declarations: dict[str, dict] = {}
    for kpi in group.kpis:
        if kpi.disclosure != DERIVED:
            continue
        owner = f"{group_key}.{kpi.name}"
        inputs = []
        for ref in kpi.derivation["inputs"]:
            if "concept" in ref:
                inputs.append(_fact_ref(cik, ref["concept"], periods,
                                        int(ref.get("periods_ago", 0)),
                                        segments, owner))
            elif "kpi" in ref:
                other = group.kpi(ref["kpi"])
                if other.disclosure == DERIVED:
                    inputs.append({"cell": other.name})
                elif other.concept:
                    # Disclosed in XBRL: inline its fact reference rather than
                    # declaring a pass-through cell that computes nothing.
                    inputs.append(_fact_ref(cik, other.concept, periods,
                                            int(ref.get("periods_ago", 0)),
                                            segments, owner))
                else:
                    key = keys.get(other.name)
                    if not key:
                        raise KpiError(
                            f"{owner}: stands on {other.name!r}, which the filer "
                            f"discloses in prose and never tags, so it has no "
                            f"facts row. Supply external_keys={{{other.name!r}: "
                            f"<record>}} naming a filing_text_disclosure record "
                            f"that cites where in the filing it was read")
                    inputs.append({"external": key})
            else:
                inputs.append(dict(ref))

        decl = {"op": kpi.derivation["op"], "inputs": inputs, "unit": kpi.unit}
        if kpi.quantize:
            decl["quantize"] = kpi.quantize
        declarations[kpi.name] = decl

    return declarations


if __name__ == "__main__":
    for key, group in load_taxonomy().items():
        print(f"\n{group.spec_ref}  {group.label}  ({key})")
        for kpi in group.kpis:
            where = (FILING_TEXT if kpi.from_prose else
                     f"xbrl:{kpi.concept}" if kpi.concept else
                     f"{kpi.derivation['op']}(...)")
            print(f"    {kpi.name:<24} {kpi.disclosure:<10} {where}")
