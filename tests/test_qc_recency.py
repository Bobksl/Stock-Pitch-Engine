"""P1.3 — C12 staleness and the framework 6.3 comparative rule.

The rule is about the SET of figures in a draft, not about each figure alone:
"every figure from the latest filed period" would ban the multi-year history
that framework 1.5 requires, and it is the second sentence — "any prior-year
figure must appear alongside its current-year comparative" — that resolves it.
So these tests are all about groups.
"""
from datetime import date

import pytest

from src.qc.recency import NO_SERIES, STALE, SeriesKey
from src.qc.report import verify_draft

MSFT = 789019
SEG = "us-gaap:StatementBusinessSegmentsAxis"
IC = "msft:IntelligentCloudMember"


def has_facts() -> bool:
    try:
        from src.facts.api import get_fact
        return get_fact(MSFT, "revenue", date(2026, 6, 30)) is not None
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not has_facts(), reason="MSFT facts not loaded in this database")


def draft(body: str, index: str) -> str:
    return f"{body}\n\n## Citation index\n\n```yaml\n{index}\n```\n"


CURRENT = "F1: {kind: fact, cik: 789019, concept: revenue, period_end: 2026-06-30}"
PRIOR = "F2: {kind: fact, cik: 789019, concept: revenue, period_end: 2025-06-30}"


# --------------------------------------------------------------------------

def test_the_latest_period_alone_is_current():
    report = verify_draft(draft("Revenue was $331.8 billion [^F1].", CURRENT))
    assert report.passed
    assert not report.stale


def test_a_prior_year_figure_alone_is_stale():
    report = verify_draft(draft("Revenue was $281.7 billion [^F2].", PRIOR))
    assert not report.passed
    assert [f.status for f in report.recency] == [STALE]
    assert report.recency[0].latest_available == date(2026, 6, 30)


def test_a_prior_year_figure_beside_its_comparative_is_admissible():
    report = verify_draft(draft(
        "Revenue reached $331.8 billion [^F1], against $281.7 billion [^F2].",
        f"{CURRENT}\n{PRIOR}"))
    assert report.passed, report.render()


def test_a_five_year_history_is_admissible_when_it_includes_the_latest_year():
    """Framework 1.5 requires margin history exhibits; C12 must not ban them."""
    body = ("Revenue: $331.8 billion [^F1], $281.7 billion [^F2], "
            "$245.1 billion [^F3], $211.9 billion [^F4], $198.3 billion [^F5].")
    index = "\n".join(
        f"F{i}: {{kind: fact, cik: 789019, concept: revenue, period_end: {pe}}}"
        for i, pe in enumerate(
            ["2026-06-30", "2025-06-30", "2024-06-30", "2023-06-30", "2022-06-30"], 1))
    report = verify_draft(draft(body, index))
    assert report.passed, report.render()


def test_staleness_is_tracked_per_series_not_per_draft():
    """A current consolidated figure does not license a stale segment figure:
    they are different series and are checked separately."""
    body = ("Revenue was $331.8 billion [^F1]. Intelligent Cloud contributed "
            "$106.3 billion [^F6].")
    index = (f"{CURRENT}\n"
             f"F6: {{kind: fact, cik: 789019, concept: revenue, "
             f"period_end: 2025-06-30, segments: {{{SEG}: {IC}}}}}")
    report = verify_draft(draft(body, index))
    assert not report.passed
    stale = [f for f in report.recency if f.status == STALE]
    assert len(stale) == 1
    assert stale[0].key == SeriesKey(cik=MSFT, concept="revenue",
                                     segments=((SEG, IC),))


def test_latest_available_comes_from_the_facts_table_not_the_draft():
    """A draft that consistently quotes an old year must not certify itself as
    current just because that year is the newest thing it mentions."""
    report = verify_draft(draft(
        "Revenue was $245.1 billion [^F3], up from $211.9 billion [^F4].",
        "F3: {kind: fact, cik: 789019, concept: revenue, period_end: 2024-06-30}\n"
        "F4: {kind: fact, cik: 789019, concept: revenue, period_end: 2023-06-30}"))
    assert not report.passed
    assert report.recency[0].status == STALE
    assert report.recency[0].latest_available == date(2026, 6, 30)


def test_as_of_moves_the_latest_period_back():
    """Point-in-time (Audit G6): as of the end of 2024, FY2024 IS the latest
    filed year, so a FY2024 figure is current rather than stale."""
    body = "Revenue was $245.1 billion [^F3]."
    index = "F3: {kind: fact, cik: 789019, concept: revenue, period_end: 2024-06-30}"
    assert verify_draft(draft(body, index), as_of=date(2024, 12, 31)).passed
    assert not verify_draft(draft(body, index)).passed


def test_model_and_external_figures_are_not_subject_to_the_series_rule():
    """A model cell's periods live in its inputs and an external record carries
    its own as-of date, so neither is checked against EDGAR's calendar."""
    md = """Margin was 46.8% [^M1].

## Model cells

```yaml
m:
  op: ratio
  quantize: "0.000001"
  inputs:
    - {cik: 789019, concept: operating_income, period_end: 2026-06-30}
    - {cik: 789019, concept: revenue, period_end: 2026-06-30}
```

## Citation index

```yaml
M1: {kind: model, cell: m}
```
"""
    report = verify_draft(md)
    assert report.passed, report.render()
    assert report.recency == []


def test_a_failed_figure_is_not_also_reported_as_stale():
    """A figure that already failed P1.2 blocks publication; repeating it as a
    staleness finding would bury the real cause under a derived one."""
    report = verify_draft(draft("Revenue was $999.9 billion [^F1].", CURRENT))
    assert not report.passed
    assert len(report.failures) == 1
    assert report.recency == []


def test_a_concept_the_filer_never_reported_is_reported_as_no_series():
    report = verify_draft(draft(
        "Capex was $1.0 billion [^F7].",
        "F7: {kind: fact, cik: 999999999, concept: capex, period_end: 2026-06-30}"))
    assert not report.passed
    # The figure fails first for a missing source; no series can be established.
    assert report.failures
    assert all(f.status != STALE for f in report.recency)


def test_series_key_identifies_a_series_by_concept_entity_and_slice():
    from src.qc.anchors import Anchor
    a = Anchor(key="F1", kind="fact",
               body={"cik": MSFT, "concept": "revenue", "period_end": "2026-06-30",
                     "segments": {SEG: IC}})
    b = Anchor(key="F2", kind="fact",
               body={"cik": MSFT, "concept": "revenue", "period_end": "2025-06-30",
                     "segments": {SEG: IC}})
    c = Anchor(key="F3", kind="fact",
               body={"cik": MSFT, "concept": "revenue", "period_end": "2026-06-30"})
    assert SeriesKey.of(a) == SeriesKey.of(b), "period is not part of the key"
    assert SeriesKey.of(a) != SeriesKey.of(c), "the segment slice is"


def test_no_series_status_is_named():
    assert NO_SERIES == "no_series"
