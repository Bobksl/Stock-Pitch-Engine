"""P3.4 — Audit R4: the per-entity retrieval quota.

R4 is listed Critical and the audit says why: "For Section 2's multi-company
panel it is a blocker, not a nicety -- one document dominating top-k breaks
cross-company comparison."

Measured on the corpus before building it, that was an understatement. The mean
top-DOCUMENT share of top-10 is 49.1%, which sounds survivable; the mean
top-ENTITY share is 98.4%, because a filer's several vintages are several
documents and one company. A panel drawn from that top-10 has one company in
it.

The quota is off by default and must stay that way. A single-company question
wants the best k passages wherever they fall, and 40 of the 44 labelled
questions are single-company. Applying the quota to those caps the one company
that was asked about, which is not a trade-off, just a bug.
"""
import pytest

from src.retrieval.chat import RETRIEVAL_SQL, retrieval_sql

TICKER_COL = 4


class TestTheQuery:
    def test_no_quota_leaves_the_measured_query_untouched(self):
        """The phase-1 retrieval baseline was measured on this exact SQL. A
        rewrite that happened to be equivalent would still make the number
        incomparable."""
        assert retrieval_sql(None) is RETRIEVAL_SQL
        assert "ROW_NUMBER" not in RETRIEVAL_SQL

    def test_the_quota_partitions_by_filer_not_by_document(self):
        sql = retrieval_sql(2)
        assert "ROW_NUMBER() OVER (PARTITION BY d.ticker" in sql
        assert "entity_rank <= %(per_entity)s" in sql

    def test_the_quota_query_does_not_leak_its_ranking_column(self):
        """entity_rank is machinery, not a result column: both the chat loop
        and the harness unpack rows POSITIONALLY against a fixed column tuple,
        so an extra column silently shifts every field one to the left."""
        projection = retrieval_sql(2).split("FROM ranked")[0]
        assert "entity_rank" not in projection.split("SELECT chunk_id")[1]


def _corpus_ready() -> bool:
    try:
        from src.db import get_conn
        with get_conn() as conn:
            return conn.execute(
                "SELECT count(DISTINCT ticker) >= 3 FROM documents").fetchone()[0]
    except Exception:
        return False


live = pytest.mark.skipif(not _corpus_ready(),
                          reason="fewer than three filers in the corpus")

QUESTION = "How do these companies describe export controls on advanced chips?"


@live
class TestAgainstTheCorpus:
    """One embed, reused: encoding on CPU is the slow part."""

    @classmethod
    def setup_class(cls):
        from src.retrieval.chat import _embed_question
        cls.qvec = _embed_question(QUESTION)

    def _rows(self, per_entity=None, k=10):
        from src.db import get_conn
        params = {"qvec": self.qvec, "ticker": None, "year": None, "k": k}
        if per_entity is not None:
            params["per_entity"] = per_entity
        with get_conn() as conn:
            return conn.execute(retrieval_sql(per_entity), params).fetchall()

    def test_without_a_quota_one_filer_takes_most_of_the_top_k(self):
        """The premise. If this stops holding, R4 stopped being a problem and
        the quota below is no longer under test."""
        tickers = [r[TICKER_COL] for r in self._rows()]
        assert max(tickers.count(t) for t in set(tickers)) > 2

    def test_the_quota_is_honoured(self):
        tickers = [r[TICKER_COL] for r in self._rows(per_entity=2)]
        assert max(tickers.count(t) for t in set(tickers)) <= 2

    def test_the_quota_widens_the_panel(self):
        """The point of R4: a cross-company question reaches more companies."""
        assert len({r[TICKER_COL] for r in self._rows(per_entity=2)}) > \
            len({r[TICKER_COL] for r in self._rows()})

    def test_results_stay_ordered_by_distance(self):
        distances = [r[-1] for r in self._rows(per_entity=2)]
        assert distances == sorted(distances)

    def test_both_queries_return_the_same_row_shape(self):
        """Both are unpacked positionally against one fixed column tuple."""
        from src.retrieval.eval.harness import _COLS
        plain, quota = self._rows(), self._rows(per_entity=2)
        assert len(plain[0]) == len(quota[0]) == len(_COLS)

    def test_a_ticker_filter_still_narrows_to_one_filer(self):
        """A quota does not widen a query that was deliberately narrowed."""
        from src.db import get_conn
        with get_conn() as conn:
            rows = conn.execute(retrieval_sql(2), {
                "qvec": self.qvec, "ticker": "NVDA", "year": None,
                "k": 10, "per_entity": 2}).fetchall()
        assert {r[TICKER_COL] for r in rows} == {"NVDA"}


@live
class TestTheHarnessMeasuresIt:
    def test_distinct_entities_is_reported_and_a_share_alone_is_not_enough(self):
        """A share is a ratio over the retrieved set, and a quota shrinks that
        set: at a quota of one a single-company question retrieves one chunk
        and scores 100%. The count is what says a panel is possible."""
        from src.retrieval.eval.harness import EvalReport, QuestionResult, Question
        chunks = [{"ticker": "NVDA", "fiscal_year": 2025},
                  {"ticker": "NVDA", "fiscal_year": 2024},
                  {"ticker": "AMD", "fiscal_year": 2025}]
        result = QuestionResult(
            question=Question(id="q", question="q", gold=()), ranks=[],
            retrieved=chunks)
        assert result.distinct_entities == 2
        assert result.top_entity_share == pytest.approx(2 / 3)
        assert result.top_doc_share == pytest.approx(1 / 3)
        assert EvalReport([result]).distinct_entities == 2

    def test_corpus_wide_selects_the_panel_shaped_questions(self):
        """40 of the 44 labelled questions set a ticker filter, so measuring a
        quota over all of them measures the cost of misapplying it."""
        from src.retrieval.eval.harness import load_questions
        questions = load_questions()
        wide = [q for q in questions if q.ticker is None]
        assert 0 < len(wide) < len(questions)
