"""P1.2 — anchors, model cells, external records, and resolution.

The DB-backed tests carry hand-checked golden values from MSFT's FY2026 10-K
(accession 0001193125-26-323660) and skip when the facts table is not loaded.
"""
from datetime import date
from decimal import Decimal

import pytest

from src.qc.anchors import CitationIndexError, parse_index
from src.qc.cells import CellError, CellRegistry
from src.qc.claims import extract_claims
from src.qc.external import EXTERNAL_KINDS, ExternalError, load_records
from src.qc.resolve import (
    MISMATCH,
    MISSING_SOURCE,
    RESOLVED,
    SCALE_UNDECLARED,
    UNANCHORED,
    UNIT_MISMATCH,
    UNKNOWN_ANCHOR,
    resolve_claim,
)

MSFT = 789019
SEG = "us-gaap:StatementBusinessSegmentsAxis"
IC = "msft:IntelligentCloudMember"
FY26 = date(2026, 6, 30)

# Hand-checked from `research_cli.py segments --ticker MSFT --cite`:
IC_REVENUE_FY26 = Decimal("137791000000")
IC_OPINC_FY26 = Decimal("56972000000")
MSFT_REVENUE_FY26 = Decimal("331839000000")


def has_facts() -> bool:
    try:
        from src.facts.api import get_fact
        return get_fact(MSFT, "revenue", FY26) is not None
    except Exception:
        return False


needs_db = pytest.mark.skipif(not has_facts(),
                              reason="MSFT facts not loaded in this database")


def only(md: str):
    claims = extract_claims(md)
    assert len(claims) == 1, [c.text for c in claims]
    return claims[0]


# --------------------------------------------------------------------------
# citation index parsing
# --------------------------------------------------------------------------

def test_index_parses_a_fenced_yaml_block():
    md = """Revenue was $331.8 billion [^F1].

## Citation index

```yaml
F1:
  kind: fact
  cik: 789019
  concept: revenue
  period_end: 2026-06-30
```
"""
    index = parse_index(md)
    assert set(index) == {"F1"}
    assert index["F1"].kind == "fact"
    assert index["F1"].cik == 789019
    assert index["F1"].period_end == date(2026, 6, 30)
    assert index["F1"].segments == {}


def test_index_parses_segments():
    md = ("## Citation index\n\n```yaml\n"
          "F7: {kind: fact, cik: 789019, concept: revenue, "
          "period_end: 2026-06-30, segments: {%s: %s}}\n```\n" % (SEG, IC))
    assert parse_index(md)["F7"].segments == {SEG: IC}


def test_absent_index_is_empty_not_an_error():
    """The failure belongs on each figure, with its span — not as one opaque
    error about a missing section."""
    assert parse_index("Revenue was $331.8 billion.") == {}


def test_illegal_provenance_kind_is_rejected():
    md = "## Citation index\n\n```yaml\nF1: {kind: vibes, cik: 1}\n```\n"
    with pytest.raises(CitationIndexError, match="kind must be one of"):
        parse_index(md)


def test_fact_anchor_requires_its_identifying_fields():
    md = "## Citation index\n\n```yaml\nF1: {kind: fact, cik: 789019}\n```\n"
    with pytest.raises(CitationIndexError, match="concept, period_end"):
        parse_index(md)


# --------------------------------------------------------------------------
# resolution against the facts table
# --------------------------------------------------------------------------

def index_for(concept="revenue", segments=None, key="F1", period_end="2026-06-30"):
    entry = {"kind": "fact", "cik": MSFT, "concept": concept,
             "period_end": period_end}
    if segments:
        entry["segments"] = segments
    import yaml
    return parse_index("## Citation index\n\n```yaml\n"
                       + yaml.safe_dump({key: entry}) + "\n```\n")


@needs_db
def test_correct_figure_resolves():
    r = resolve_claim(only("Revenue was $331.8 billion [^F1]."), index_for())
    assert r.status == RESOLVED
    assert r.actual == MSFT_REVENUE_FY26
    assert "0001193125-26-323660" in r.citation


@needs_db
def test_corrupted_figure_does_not_resolve():
    r = resolve_claim(only("Revenue was $331.9 billion [^F1]."), index_for())
    assert r.status == MISMATCH
    assert r.actual == MSFT_REVENUE_FY26
    assert "331,839,000,000" in r.detail


@needs_db
def test_segment_figure_resolves_through_its_member():
    idx = index_for(segments={SEG: IC})
    r = resolve_claim(only("Intelligent Cloud revenue was $137,791 million [^F1]."), idx)
    assert r.status == RESOLVED and r.actual == IC_REVENUE_FY26


@needs_db
def test_anchor_pointing_at_the_wrong_segment_is_caught():
    """The value is right for Intelligent Cloud but the anchor cites the
    consolidated total — a mis-citation, and a failure."""
    r = resolve_claim(only("Intelligent Cloud revenue was $137,791 million [^F1]."),
                      index_for())
    assert r.status == MISMATCH
    assert r.actual == MSFT_REVENUE_FY26


@needs_db
def test_anchor_pointing_at_the_wrong_period_is_caught():
    idx = index_for(segments={SEG: IC}, period_end="2025-06-30")
    r = resolve_claim(only("Intelligent Cloud revenue was $137,791 million [^F1]."), idx)
    assert r.status == MISMATCH
    assert r.actual == Decimal("106265000000")


@needs_db
def test_nonexistent_fact_is_reported_as_a_missing_source():
    idx = index_for(period_end="1999-06-30")
    r = resolve_claim(only("Revenue was $331.8 billion [^F1]."), idx)
    assert r.status == MISSING_SOURCE


@needs_db
def test_as_of_gives_the_point_in_time_answer():
    """Before the FY2026 10-K was filed, FY2026 revenue was not knowable."""
    idx = index_for()
    claim = only("Revenue was $331.8 billion [^F1].")
    assert resolve_claim(claim, idx, as_of=date(2024, 12, 31)).status == MISSING_SOURCE
    assert resolve_claim(claim, idx).status == RESOLVED


@needs_db
def test_scale_corruption_is_caught_and_the_fix_is_named():
    r = resolve_claim(only("Revenue was $331.8 million [^F1]."), index_for())
    assert r.status == MISMATCH
    assert "scale 1,000,000,000" in r.detail


@needs_db
def test_unit_mismatch_is_caught_even_when_the_digits_agree():
    idx = index_for(concept="diluted_shares")
    from src.facts.api import get_fact
    shares = get_fact(MSFT, "diluted_shares", FY26)
    written = f"${shares.value / Decimal('1e6'):.1f} million"
    r = resolve_claim(only(f"The figure is {written} [^F1]."), idx)
    assert r.status == UNIT_MISMATCH


# --------------------------------------------------------------------------
# failures that need no database
# --------------------------------------------------------------------------

def test_unanchored_figure_is_a_hard_failure():
    r = resolve_claim(only("Revenue was $331.8 billion."), {})
    assert r.status == UNANCHORED
    assert not r.ok


def test_anchor_with_no_index_entry_is_a_hard_failure():
    r = resolve_claim(only("Revenue was $331.8 billion [^F9]."), {})
    assert r.status == UNKNOWN_ANCHOR


def test_undeclared_scale_fails_before_any_lookup():
    md = ("| Segment | Revenue |\n|---|---|\n| Intelligent Cloud | 137,791 [^F1] |\n")
    r = resolve_claim(only(md), index_for())
    assert r.status == SCALE_UNDECLARED
    assert "declares no unit" in r.detail


# --------------------------------------------------------------------------
# model cells -- recomputed, not trusted
# --------------------------------------------------------------------------

CELLS_YAML = f"""
ic_margin_fy26:
  op: ratio
  quantize: "0.0001"
  unit: pure
  inputs:
    - {{cik: {MSFT}, concept: operating_income, period_end: 2026-06-30,
        segments: {{{SEG}: {IC}}}}}
    - {{cik: {MSFT}, concept: revenue, period_end: 2026-06-30,
        segments: {{{SEG}: {IC}}}}}
"""


@needs_db
def test_model_cell_is_recomputed_from_its_cited_facts():
    cells = CellRegistry.from_yaml(CELLS_YAML)
    result = cells.compute("ic_margin_fy26")
    assert result.value == (IC_OPINC_FY26 / IC_REVENUE_FY26).quantize(Decimal("0.0001"))
    assert result.value == Decimal("0.4135")
    assert len(result.inputs) == 2
    assert all("0001193125-26-323660" in f.citation for f in result.inputs)


@needs_db
def test_derived_percentage_resolves_against_its_model_cell():
    md = ("Intelligent Cloud ran a 41.3% margin [^M1].\n\n"
          "## Citation index\n\n```yaml\n"
          "M1: {kind: model, cell: ic_margin_fy26}\n```\n")
    claim = extract_claims(md)[0]
    r = resolve_claim(claim, parse_index(md), cells=CellRegistry.from_yaml(CELLS_YAML))
    assert r.status == RESOLVED
    assert "model:ic_margin_fy26 = ratio" in r.citation


@needs_db
def test_a_wrong_margin_fails_even_though_the_cell_is_declared():
    """The point of recomputation: the cell cannot launder a bad number."""
    md = ("Intelligent Cloud ran a 48.0% margin [^M1].\n\n"
          "## Citation index\n\n```yaml\n"
          "M1: {kind: model, cell: ic_margin_fy26}\n```\n")
    r = resolve_claim(extract_claims(md)[0], parse_index(md),
                      cells=CellRegistry.from_yaml(CELLS_YAML))
    assert r.status == MISMATCH


def test_unknown_op_is_rejected():
    cells = CellRegistry.from_yaml("x: {op: vibes, inputs: [{literal: 1, note: n}]}")
    with pytest.raises(CellError, match="unknown op"):
        cells.compute("x")


def test_wrong_arity_is_rejected():
    cells = CellRegistry.from_yaml(
        "x: {op: ratio, inputs: [{literal: 1, note: n}]}")
    with pytest.raises(CellError, match="takes 2 inputs"):
        cells.compute("x")


def test_a_cycle_is_reported_not_hung():
    cells = CellRegistry.from_yaml(
        "a: {op: sum, inputs: [{cell: b}]}\nb: {op: sum, inputs: [{cell: a}]}")
    with pytest.raises(CellError, match="defined in terms of itself"):
        cells.compute("a")


def test_literal_inputs_require_a_note_saying_where_they_came_from():
    cells = CellRegistry.from_yaml("x: {op: sum, inputs: [{literal: 42}]}")
    with pytest.raises(CellError, match="requires a 'note'"):
        cells.compute("x")


def test_cells_compose():
    cells = CellRegistry.from_yaml("""
base: {op: sum, inputs: [{literal: 10, note: hand-checked}]}
doubled: {op: product, inputs: [{cell: base}, {literal: 2, note: hand-checked}]}
""")
    assert cells.compute("doubled").value == Decimal("20")


def test_growth_and_difference_arithmetic():
    cells = CellRegistry.from_yaml("""
g: {op: growth, inputs: [{literal: 331839, note: fy26}, {literal: 281724, note: fy25}]}
d: {op: difference, inputs: [{literal: 331839, note: fy26}, {literal: 281724, note: fy25}]}
""")
    assert cells.compute("d").value == Decimal("50115")
    # 331839 / 281724 - 1 = 0.177894... -> 17.8%
    assert cells.compute("g").value.quantize(Decimal("0.0001")) == Decimal("0.1779")


def test_division_by_zero_is_a_cell_error_not_a_crash():
    cells = CellRegistry.from_yaml(
        "x: {op: ratio, inputs: [{literal: 1, note: n}, {literal: 0, note: n}]}")
    with pytest.raises(CellError, match="denominator is zero"):
        cells.compute("x")


# --------------------------------------------------------------------------
# external records -- the closed vocabulary is the whole safeguard
# --------------------------------------------------------------------------

EXTERNAL_YAML = """
best_rev_fy27:
  kind: consensus_estimate
  value: 372500000000
  unit: USD
  source: Bloomberg BEst
  as_of: 2026-08-15
  ticker: MSFT
"""


def test_external_record_resolves_a_consensus_figure():
    md = ("Consensus expects $372.5 billion [^E1].\n\n"
          "## Citation index\n\n```yaml\n"
          "E1: {kind: ext, record: best_rev_fy27}\n```\n")
    r = resolve_claim(extract_claims(md)[0], parse_index(md),
                      externals=load_records(EXTERNAL_YAML))
    assert r.status == RESOLVED
    assert "Bloomberg BEst" in r.citation and "2026-08-15" in r.citation


def test_a_wrong_consensus_figure_still_fails():
    md = ("Consensus expects $380.0 billion [^E1].\n\n"
          "## Citation index\n\n```yaml\n"
          "E1: {kind: ext, record: best_rev_fy27}\n```\n")
    r = resolve_claim(extract_claims(md)[0], parse_index(md),
                      externals=load_records(EXTERNAL_YAML))
    assert r.status == MISMATCH


def test_external_kind_outside_the_vocabulary_is_rejected():
    """Without this, the class is an allowlist: any figure failing the facts
    check could be re-declared as external and pass."""
    with pytest.raises(ExternalError, match="not an external-only"):
        load_records("seg_rev: {kind: segment_revenue, value: 1, unit: USD,"
                     " source: me, as_of: 2026-01-01}\n")


def test_external_record_requires_source_and_as_of():
    with pytest.raises(ExternalError, match="source"):
        load_records("x: {kind: market_price, value: 1, unit: USD,"
                     " as_of: 2026-01-01}\n")


def test_the_vocabulary_covers_the_framework_cases():
    assert set(EXTERNAL_KINDS) == {"consensus_estimate", "market_price",
                                   "beta_input", "peer_market_data", "macro_series"}


def test_missing_external_record_is_a_missing_source():
    md = ("Consensus expects $372.5 billion [^E1].\n\n"
          "## Citation index\n\n```yaml\n"
          "E1: {kind: ext, record: nope}\n```\n")
    r = resolve_claim(extract_claims(md)[0], parse_index(md), externals={})
    assert r.status == MISSING_SOURCE


def test_absent_external_store_is_empty_not_an_error(tmp_path):
    assert load_records(tmp_path / "does_not_exist") == {}
