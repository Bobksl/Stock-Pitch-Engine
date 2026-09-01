"""P1.4 — the retrieval eval harness (Audit R7).

Most of this is pure metric arithmetic with hand-checked values. The last test
runs the real retriever over the real corpus and holds a floor, so a change to
chunking, embedding or the segmenter that quietly degrades retrieval fails here
rather than surfacing later as bad prose.
"""
from pathlib import Path

import pytest

from src.retrieval.eval.harness import (
    ANY_YEAR,
    EvalReport,
    GoldTarget,
    Question,
    QuestionResult,
    load_questions,
    run_eval,
)


def chunk(ticker="MSFT", year=2026, section="item_7", content="text"):
    return {"ticker": ticker, "fiscal_year": year, "section_key": section,
            "content": content, "section": section, "distance": 0.3}


def question(gold, **kw):
    return Question(id="q", question="?", gold=tuple(gold), **kw)


# --------------------------------------------------------------------------
# gold labels
# --------------------------------------------------------------------------

def test_a_pinned_target_requires_the_year():
    g = GoldTarget("MSFT", 2026, "item_7")
    assert g.matches(chunk())
    assert not g.matches(chunk(year=2025))
    assert not g.matches(chunk(ticker="NVDA"))
    assert not g.matches(chunk(section="item_1"))


def test_an_any_year_target_ignores_the_year():
    """The corpus holds five near-identical vintages of each filing; for
    narrative that is unchanged between them, the year is not what is being
    measured."""
    g = GoldTarget("MSFT", ANY_YEAR, "item_7")
    assert g.matches(chunk(year=2026))
    assert g.matches(chunk(year=2022))
    assert not g.matches(chunk(ticker="AAPL", year=2022))
    assert g.year_agnostic


def test_must_match_narrows_a_location_label():
    q = question([GoldTarget("MSFT", ANY_YEAR, "item_7")], must_match="Intelligent Cloud")
    assert q.relevant(chunk(content="Intelligent Cloud revenue increased"))
    assert not q.relevant(chunk(content="Gaming revenue decreased"))


def test_gold_labels_are_locations_not_chunk_ids():
    """A chunk id would rot the first time chunk size or the segmenter changed,
    which is exactly what this harness exists to evaluate."""
    assert set(GoldTarget.__dataclass_fields__) == {
        "ticker", "fiscal_year", "section_key"}


# --------------------------------------------------------------------------
# metrics
# --------------------------------------------------------------------------

def result(ranks, gold=None, retrieved=None):
    gold = gold or [GoldTarget("MSFT", 2026, "item_7")]
    return QuestionResult(question=question(gold), ranks=ranks,
                          retrieved=retrieved or [])


def test_hit_at_k():
    r = result([4])
    assert not r.hit_at(1) and not r.hit_at(3)
    assert r.hit_at(4) and r.hit_at(10)


def test_reciprocal_rank_uses_the_first_relevant_chunk():
    assert result([3, 7]).reciprocal_rank == pytest.approx(1 / 3)
    assert result([]).reciprocal_rank == 0.0


def test_mrr_is_the_mean_over_questions():
    report = EvalReport([result([1]), result([2]), result([])])
    assert report.mrr == pytest.approx((1.0 + 0.5 + 0.0) / 3)


def test_hit_rate_is_the_share_of_questions_with_any_relevant_chunk():
    report = EvalReport([result([1]), result([9]), result([])])
    assert report.hit_rate(5) == pytest.approx(1 / 3)
    assert report.hit_rate(10) == pytest.approx(2 / 3)


def test_recall_counts_gold_targets_reached():
    gold = [GoldTarget("MSFT", 2026, "item_7"), GoldTarget("MSFT", 2026, "item_8")]
    retrieved = [chunk(section="item_7"), chunk(section="item_1"),
                 chunk(section="item_8")]
    r = QuestionResult(question=question(gold), ranks=[1, 3], retrieved=retrieved)
    assert r.recall_at(1) == pytest.approx(0.5)
    assert r.recall_at(3) == pytest.approx(1.0)


def test_top_doc_share_measures_monopolisation():
    """The measurement behind Audit R4: one filing dominating top-k breaks a
    cross-company panel."""
    same = [chunk(year=2026) for _ in range(4)]
    mixed = [chunk(year=2026), chunk(year=2025), chunk(ticker="NVDA"),
             chunk(ticker="AAPL")]
    gold = [GoldTarget("MSFT", 2026, "item_7")]
    assert QuestionResult(question(gold), ranks=[],
                          retrieved=same).top_doc_share == 1.0
    assert QuestionResult(question(gold), ranks=[],
                          retrieved=mixed).top_doc_share == 0.25


def test_split_separates_pinned_from_agnostic_questions():
    pinned = result([1], gold=[GoldTarget("MSFT", 2026, "item_7")])
    agnostic = result([2], gold=[GoldTarget("MSFT", ANY_YEAR, "item_7")])
    a, b = EvalReport([pinned, agnostic]).split()
    assert a.n == 1 and b.n == 1
    assert a.results[0] is pinned


def test_empty_report_does_not_divide_by_zero():
    report = EvalReport([])
    assert report.mrr == 0.0 and report.hit_rate(5) == 0.0


# --------------------------------------------------------------------------
# the shipped question set
# --------------------------------------------------------------------------

def test_the_question_set_loads_and_is_well_formed():
    questions = load_questions()
    assert len(questions) >= 40, "the set should cover the corpus, not sample it"
    assert len({q.id for q in questions}) == len(questions), "ids must be unique"
    for q in questions:
        assert q.gold, f"{q.id} has no gold label"
        assert q.question.strip().endswith("?") or "?" in q.question


def test_the_question_set_spans_every_filer_and_the_main_items():
    questions = load_questions()
    tickers = {g.ticker for q in questions for g in q.gold}
    assert tickers == {"MSFT", "NVDA", "AAPL", "AMD"}
    items = {g.section_key for q in questions for g in q.gold}
    assert {"item_1", "item_1a", "item_7", "item_8"} <= items


def test_year_pinned_questions_set_the_year_filter():
    """A pinned question must ask the way production asks -- with the year as a
    metadata filter -- or it is measuring the embedding's taste in vintages."""
    for q in load_questions():
        if q.gold[0].year_agnostic:
            continue
        assert q.year == q.gold[0].fiscal_year, (
            f"{q.id} pins FY{q.gold[0].fiscal_year} but does not filter on it")


# --------------------------------------------------------------------------
# the real retriever over the real corpus
# --------------------------------------------------------------------------

def corpus_ready() -> bool:
    try:
        from src.db import get_conn
        with get_conn() as c:
            return c.execute(
                "SELECT count(*) FROM chunks WHERE embedding IS NOT NULL"
            ).fetchone()[0] > 5000
    except Exception:
        return False


@pytest.mark.skipif(not corpus_ready(), reason="embedded corpus not loaded")
def test_retrieval_holds_its_measured_floor():
    """Regression floor, set below the measured baseline rather than at it.

    Measured on the 20-filing corpus with BGE-M3: hit@5 88.6%, hit@10 93.2%,
    MRR 0.820. The floors below leave headroom for embedding nondeterminism
    while still catching a real degradation from a chunking or segmenter change.
    """
    report = run_eval()
    assert report.n >= 40
    assert report.hit_rate(5) >= 0.80, report.render()
    assert report.hit_rate(10) >= 0.85, report.render()
    assert report.mrr >= 0.70, report.render()


@pytest.mark.skipif(not corpus_ready(), reason="embedded corpus not loaded")
def test_the_questions_yaml_lives_where_the_harness_looks_for_it():
    from src.retrieval.eval.harness import QUESTIONS_PATH
    assert Path(QUESTIONS_PATH).exists()
