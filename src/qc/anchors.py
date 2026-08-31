"""P1.2 — the citation index: what a draft's figures claim to be sourced from.

Why an anchor is required rather than a table search
----------------------------------------------------
The obvious design is to take a figure and look for a fact that matches it. It
does not work, and the measurement is not close. Taking 200 real MSFT facts,
corrupting each by 0.8bn, and asking whether ANY fact still falls inside the
claim's tolerance band:

    "$X.Y billion" claims        192 / 200 corrupted claims still match
    4-significant-figure claims   17 / 200

MSFT alone has 17,279 current USD facts. At the granularity a pitch headline is
written to, the facts table is dense enough that a wrong number almost always
finds an innocent-looking home. A search-based verifier would pass a corrupted
headline figure 96% of the time -- it would fail the one test Phase 1 exists to
pass.

So the draft carries its provenance and the verifier checks that the cited row
says what the prose says. Framework 6.4 already requires this ("no free-floating
figures") and framework 9 already provides the place for it (the appendix
citation index).

Format
------
A figure carries a standard Markdown footnote marker, and the index maps it:

    Intelligent Cloud revenue was $137,791 million [^F7].

    ## Citation index

    ```yaml
    F7:
      kind: fact
      cik: 789019
      concept: revenue
      period_end: 2026-06-30
      segments: {us-gaap:StatementBusinessSegmentsAxis: msft:IntelligentCloudMember}
    ```

Three provenance kinds are legal, and no others:

  `fact`   a facts-table row, resolved through the concept map (facts/api.py)
  `model`  a derived cell, recomputed from cited facts (cells.py)
  `ext`    a declared external source, for figures that have no facts row by
           construction -- consensus estimates, market prices, beta inputs
           (external.py)

A figure with no anchor, or an anchor with no index entry, is a hard failure.
"""
import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any

import yaml

KIND_FACT, KIND_MODEL, KIND_EXT = "fact", "model", "ext"
KINDS = (KIND_FACT, KIND_MODEL, KIND_EXT)

_INDEX_RE = re.compile(
    r"^#{1,6}[ \t]*Citation index[ \t]*$(?P<body>.*?)(?=^#{1,6}[ \t]|\Z)",
    re.MULTILINE | re.DOTALL | re.I)
_YAML_BLOCK_RE = re.compile(r"```[ \t]*(?:yaml|yml)?[ \t]*\n(?P<yaml>.*?)^```",
                            re.MULTILINE | re.DOTALL)


class CitationIndexError(ValueError):
    """The citation index is missing, malformed, or declares an illegal kind."""


@dataclass(frozen=True)
class Anchor:
    """One entry of the citation index."""

    key: str
    kind: str
    body: dict[str, Any] = field(default_factory=dict)

    # -- fact anchors ------------------------------------------------------
    @property
    def cik(self) -> int | None:
        return self.body.get("cik")

    @property
    def concept(self) -> str | None:
        return self.body.get("concept")

    @property
    def period_end(self) -> date | None:
        value = self.body.get("period_end")
        return date.fromisoformat(value) if isinstance(value, str) else value

    @property
    def segments(self) -> dict[str, str]:
        return dict(self.body.get("segments") or {})

    def describe(self) -> str:
        if self.kind == KIND_FACT:
            seg = ", ".join(f"{k}={v}" for k, v in sorted(self.segments.items()))
            return (f"fact {self.concept} cik={self.cik} period={self.period_end}"
                    + (f" [{seg}]" if seg else " [consolidated]"))
        if self.kind == KIND_MODEL:
            return f"model cell {self.body.get('cell')}"
        return f"external {self.body.get('source')} as of {self.body.get('as_of')}"


_REQUIRED: dict[str, tuple[str, ...]] = {
    KIND_FACT: ("cik", "concept", "period_end"),
    KIND_MODEL: ("cell",),
    KIND_EXT: ("record",),
}


def parse_index(md: str) -> dict[str, Anchor]:
    """The draft's citation index, keyed by anchor key.

    An absent index is legal and yields {} -- the resulting failure should be
    "figure X has no provenance", reported per figure with its span, not one
    opaque error about a missing section.
    """
    section = _INDEX_RE.search(md)
    if not section:
        return {}

    body = section.group("body")
    blocks = [m.group("yaml") for m in _YAML_BLOCK_RE.finditer(body)]
    raw = "\n".join(blocks) if blocks else body

    try:
        loaded = yaml.safe_load(raw) or {}
    except yaml.YAMLError as exc:
        raise CitationIndexError(f"citation index is not valid YAML: {exc}") from None
    if not isinstance(loaded, dict):
        raise CitationIndexError(
            "citation index must be a mapping of anchor key -> provenance")

    anchors: dict[str, Anchor] = {}
    for key, entry in loaded.items():
        key = str(key)
        if not isinstance(entry, dict):
            raise CitationIndexError(f"anchor {key}: entry must be a mapping")
        kind = entry.get("kind")
        if kind not in KINDS:
            raise CitationIndexError(
                f"anchor {key}: kind must be one of {KINDS}, got {kind!r}")
        missing = [f for f in _REQUIRED[kind] if entry.get(f) is None]
        if missing:
            raise CitationIndexError(
                f"anchor {key}: {kind} provenance requires {', '.join(missing)}")
        anchors[key] = Anchor(key=key, kind=kind,
                              body={k: v for k, v in entry.items() if k != "kind"})
    return anchors
