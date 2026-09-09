"""P3.3 — rendering a draft: prose from the LLM, every figure from Python.

Framework P1 says the LLM never computes a number that appears in an output.
The gate already catches a violation after the fact -- a hallucinated figure
fails to resolve -- but catching is weaker than preventing, so the boundary is
structural here instead.

The LLM writes prose containing named SLOTS and no numerals:

    Semiconductor Solutions sells {semis_revenue_share} of the revenue.

`render` substitutes the figure and its citation marker together, from a
`Figure` the builder computed in `Decimal`. A numeral surviving in the template
is a hard failure, reported as `llm_computed_arithmetic` -- the Class A rule
that already exists for exactly this. There is no path by which prose supplies
a number: the slot name selects a figure, and the figure carries its own value
and provenance.

This is the same move `exceptions.py` makes by refusing at load time rather
than at check time, and `TypeField` by having no constructor that accepts an
asserted dominance.

Content-addressed markers
-------------------------
6.4 requires markers to be content-addressed rather than sequential, because
"editing prose must not silently renumber markers and invalidate the index".
Sequential keys break that the first time a sentence is moved. A marker here is
a short digest of the provenance it points at, so the same fact always gets the
same marker, two slots citing one fact share it, and reordering prose changes
nothing. The hand-written phase-1 fixtures use F1/M1 because a person wrote
them; generated drafts do not.
"""
import hashlib
import json
import re
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from src.qc.anchors import KIND_EXT, KIND_FACT, KIND_MODEL
from src.qc.claims import extract_claims
from src.qc.findings import Finding
from src.qc.rules import rule

#: Characters of digest in a marker. Six is 24 bits: collisions within one
#: draft's few dozen figures are not a practical concern, and a longer marker
#: makes the prose harder for a person to read past.
DIGEST_CHARS = 6

_SLOT_RE = re.compile(r"\{([a-z][a-z0-9_]*)\}")

_KIND_PREFIX = {KIND_FACT: "F", KIND_MODEL: "M", KIND_EXT: "E"}


class TemplateError(ValueError):
    """The prose template cannot be rendered as written."""


@dataclass(frozen=True)
class Figure:
    """One number, its rendering, and the provenance it resolves to."""

    name: str
    #: Exactly as it should appear in the prose: '57.69%', '$63,887 million'.
    text: str
    kind: str
    #: The citation-index entry, minus `kind`.
    body: dict[str, Any]
    #: For a model figure, its cell declaration. None otherwise.
    cell: dict[str, Any] | None = None
    #: The computed value, kept for tests and for the exhibit builders.
    value: Decimal | None = None

    @property
    def marker(self) -> str:
        """Content-addressed: a digest of what this figure cites (6.4)."""
        payload = json.dumps(self.body, sort_keys=True, default=str)
        digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        return f"{_KIND_PREFIX[self.kind]}{digest[:DIGEST_CHARS]}"

    @property
    def rendered(self) -> str:
        return f"{self.text} [^{self.marker}]"


@dataclass
class Draft:
    """A rendered section, and the pieces the gate will read back out of it."""

    body: str
    figures: dict[str, Figure] = field(default_factory=dict)
    #: Every declared cell, cited or not. An intermediate that a cited cell
    #: stands on is emitted from here; see `cell_closure`.
    cells: dict[str, dict[str, Any]] = field(default_factory=dict)

    @property
    def markers(self) -> dict[str, Figure]:
        return {f.marker: f for f in self.figures.values()}

    def cell_closure(self) -> dict[str, dict[str, Any]]:
        """The cited model cells AND everything they are computed from.

        A cell can stand on another cell: a segment profit share divides by a
        segment total that is itself a sum, because the filer reports the parts
        and never the total. Emitting only the CITED cells leaves the draft
        carrying a declaration that refers to one which is not there, and
        `cells.py` then refuses to compute it -- correctly, and confusingly.
        The intermediate is cited by no figure and must still be published: it
        is part of how the cited number was made.
        """
        declared = dict(self.cells)
        for figure in self.figures.values():
            if figure.kind == KIND_MODEL and figure.cell:
                declared.setdefault(figure.body["cell"], figure.cell)

        needed: dict[str, dict[str, Any]] = {}
        stack = [f.body["cell"] for f in self.figures.values()
                 if f.kind == KIND_MODEL]
        while stack:
            name = stack.pop()
            if name in needed or name not in declared:
                continue
            needed[name] = declared[name]
            for ref in declared[name].get("inputs", []):
                if isinstance(ref, dict) and "cell" in ref:
                    stack.append(ref["cell"])
        return needed

    def markdown(self) -> str:
        parts = [self.body.rstrip("\n")]
        cells = self.cell_closure()
        if cells:
            parts.append("## Model cells\n\n```yaml\n"
                         + _yaml_block(cells) + "```")
        index = {f.marker: {"kind": f.kind, **f.body}
                 for f in self.markers.values()}
        parts.append("## Citation index\n\n```yaml\n"
                     + _yaml_block(index) + "```")
        return "\n\n".join(parts) + "\n"


def _yaml_block(mapping: dict) -> str:
    import yaml
    return yaml.safe_dump(mapping, sort_keys=True, default_flow_style=False,
                          allow_unicode=True, width=88)


def bare_numeral_finding(template: str,
                         blocks: dict[str, str] | None = None) -> Finding | None:
    """P1 — a figure the LLM wrote rather than one Python computed.

    Run on the template BEFORE substitution, with every slot blanked, so the
    only numerals it can see are ones the prose supplied itself. Exhibit blocks
    are blanked too: a segment mix table is generated by Python from cited
    facts and its figures already carry their markers, so the numerals in it
    are not the LLM writing numbers -- they are the same figures, laid out.
    """
    del blocks                      # blanked by the shared slot pattern
    blanked = _SLOT_RE.sub(lambda m: " " * (m.end() - m.start()), template)
    claims = extract_claims(blanked)
    if not claims:
        return None
    where = ", ".join(f"line {c.line}: {c.text!r}" for c in claims)
    return Finding(
        rule=rule("llm_computed_arithmetic"),
        detail=(f"{len(claims)} numeral(s) are written into the prose template "
                f"rather than supplied by a slot - {where}. Framework P1: the "
                f"LLM narrates figures computed in Python, and a slot is how it "
                f"asks for one."))


def render(template: str, figures: dict[str, Figure],
           blocks: dict[str, str] | None = None,
           cells: dict[str, dict[str, Any]] | None = None) -> Draft:
    """Substitute every slot with its figure and citation marker.

    `blocks` are Markdown fragments Python generated -- the 1.5 exhibits. They
    occupy slots like a figure does, and the figures they cite are counted as
    used, so an exhibit is not a hole in either the P1 check or the
    nothing-uncited check.

    Refuses rather than degrades, in three ways: a numeral in the prose, a slot
    nothing fills, and a figure nothing cites. The last matters because a
    citation index listing provenance no figure refers to is how a draft comes
    to look better sourced than it is.

    Usage is measured by scanning the FINAL body for each marker rather than by
    counting slot substitutions, so a figure cited only from inside an exhibit
    counts exactly like one cited from prose.
    """
    blocks = blocks or {}
    if finding := bare_numeral_finding(template, blocks):
        raise TemplateError(finding.detail)

    missing: set[str] = set()

    def swap(match: re.Match) -> str:
        name = match.group(1)
        if name in blocks:
            return blocks[name]
        figure = figures.get(name)
        if figure is None:
            missing.add(name)
            return match.group(0)
        return figure.rendered

    body = _SLOT_RE.sub(swap, template)

    if missing:
        raise TemplateError(
            f"the template asks for {sorted(missing)}, which the evidence does "
            f"not carry. Available: {sorted(figures) + sorted(blocks)}")

    used = {name: f for name, f in figures.items() if f"[^{f.marker}]" in body}
    unused = sorted(set(figures) - set(used))
    if unused:
        raise TemplateError(
            f"{unused} were computed but nothing cites them. A citation index "
            f"carrying provenance no figure refers to makes a draft look better "
            f"sourced than it is; drop the figure or cite it")

    return Draft(body=body, figures=used, cells=dict(cells or {}))
