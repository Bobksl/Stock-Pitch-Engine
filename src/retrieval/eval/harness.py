"""P1.4 — the retrieval eval harness (Audit R7).

    "Trust in retrieval must be measured before prose is built on it."

Phase 1 is deliberately sequenced before generation, and this is the half of it
that covers narrative. Numbers are checked by src/qc; narrative comes from
vector retrieval, and nothing else in the pipeline can tell you whether the
chunk a sentence was written from was the right chunk.

Labelling by location, not by chunk id
--------------------------------------
Gold labels are (ticker, fiscal_year, section_key) -- the Item the answer lives
in -- with an optional pattern the chunk text must contain. They are NOT chunk
ids. A chunk id is invalidated by any change to chunk size, overlap, or the
segmenter, which is exactly the sort of change this harness exists to evaluate;
a gold set that silently rots the first time the chunker is tuned measures
nothing. An Item is a stable, human-checkable answer to "where is this stated".

Metrics
-------
    hit@k       questions with at least one relevant chunk in the top k
    recall@k    share of a question's gold targets reached in the top k
                (identical to hit@k for the single-target questions)
    MRR         mean reciprocal rank of the first relevant chunk

`top_doc_share` is reported alongside them: the mean share of the top k taken by
whichever single document dominates it. It is not a quality metric -- it is the
measurement behind Audit R4, since a cross-company panel breaks when one filing
monopolises top-k, and it should be watched before Section 2 is built on it.
"""
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from src.config import PROJECT_ROOT
from src.db import get_conn
from src.retrieval.chat import RETRIEVAL_SQL

QUESTIONS_PATH = PROJECT_ROOT / "eval" / "questions.yaml"
DEFAULT_KS = (1, 3, 5, 10)


ANY_YEAR = "any"


@dataclass(frozen=True)
class GoldTarget:
    """Where an answer actually lives.

    `fiscal_year` may be a year or ANY_YEAR, and the distinction is the most
    important thing in this file. The corpus holds five near-identical vintages
    of each filing, and most narrative answers -- how AMD describes foundry
    risk, how Microsoft describes its workforce -- are present in all five and
    barely reworded between them. Pinning such a question to one year does not
    measure whether retrieval found the right passage; it measures whether the
    embedding happened to prefer one vintage of an almost identical passage,
    which is a coin toss dressed up as a score.

    Recency is a metadata filter in this pipeline, not something the embedding
    is asked to infer: rag_chat.retrieve takes a `year`, and a pitch is always
    written about a known fiscal year. So questions where the year matters set
    the `year` retrieval filter and pin the gold year, and the rest use
    ANY_YEAR and measure what they actually intend to -- can retrieval find the
    right company and the right Item.
    """

    ticker: str
    fiscal_year: int | str
    section_key: str

    @property
    def year_agnostic(self) -> bool:
        return self.fiscal_year == ANY_YEAR

    def matches(self, chunk: dict) -> bool:
        if chunk["ticker"] != self.ticker:
            return False
        if not self.year_agnostic and chunk["fiscal_year"] != self.fiscal_year:
            return False
        return chunk.get("section_key") == self.section_key

    def __str__(self) -> str:
        year = "FY*" if self.year_agnostic else f"FY{self.fiscal_year}"
        return f"{self.ticker} {year} {self.section_key}"


@dataclass(frozen=True)
class Question:
    id: str
    question: str
    gold: tuple[GoldTarget, ...]
    must_match: str | None = None      # regex the chunk content must contain
    ticker: str | None = None          # retrieval filter; None searches the corpus
    year: int | None = None
    note: str = ""

    def relevant(self, chunk: dict) -> bool:
        import re
        if not any(g.matches(chunk) for g in self.gold):
            return False
        if self.must_match and not re.search(self.must_match, chunk["content"],
                                             re.I | re.S):
            return False
        return True


@dataclass
class QuestionResult:
    question: Question
    ranks: list[int]                   # 1-based ranks of relevant chunks
    covered: set[GoldTarget] = field(default_factory=set)
    retrieved: list[dict] = field(default_factory=list)

    def hit_at(self, k: int) -> bool:
        return any(r <= k for r in self.ranks)

    def recall_at(self, k: int) -> float:
        if not self.question.gold:
            return 0.0
        reached = {g for g in self.question.gold
                   for i, c in enumerate(self.retrieved[:k]) if g.matches(c)}
        return len(reached) / len(self.question.gold)

    @property
    def reciprocal_rank(self) -> float:
        return 1.0 / min(self.ranks) if self.ranks else 0.0

    @property
    def top_doc_share(self) -> float:
        """Largest share of the retrieved set held by one document."""
        if not self.retrieved:
            return 0.0
        counts: dict[tuple, int] = {}
        for c in self.retrieved:
            key = (c["ticker"], c["fiscal_year"])
            counts[key] = counts.get(key, 0) + 1
        return max(counts.values()) / len(self.retrieved)


@dataclass
class EvalReport:
    results: list[QuestionResult]
    ks: tuple[int, ...] = DEFAULT_KS

    @property
    def n(self) -> int:
        return len(self.results)

    def hit_rate(self, k: int) -> float:
        return sum(r.hit_at(k) for r in self.results) / self.n if self.n else 0.0

    def recall(self, k: int) -> float:
        return (sum(r.recall_at(k) for r in self.results) / self.n) if self.n else 0.0

    @property
    def mrr(self) -> float:
        return (sum(r.reciprocal_rank for r in self.results) / self.n) if self.n else 0.0

    @property
    def top_doc_share(self) -> float:
        return (sum(r.top_doc_share for r in self.results) / self.n) if self.n else 0.0

    def misses(self, k: int) -> list[QuestionResult]:
        return [r for r in self.results if not r.hit_at(k)]

    def split(self) -> tuple["EvalReport", "EvalReport"]:
        """(year-pinned, year-agnostic) — they measure different things."""
        pinned = [r for r in self.results
                  if r.question.gold and not r.question.gold[0].year_agnostic]
        agnostic = [r for r in self.results
                    if r.question.gold and r.question.gold[0].year_agnostic]
        return EvalReport(pinned, self.ks), EvalReport(agnostic, self.ks)

    def by_section(self, k: int) -> dict[str, tuple[int, int]]:
        """section_key -> (hits, asked), from each question's first gold target."""
        out: dict[str, list[int]] = {}
        for r in self.results:
            if not r.question.gold:
                continue
            key = r.question.gold[0].section_key
            bucket = out.setdefault(key, [0, 0])
            bucket[0] += int(r.hit_at(k))
            bucket[1] += 1
        return {k_: (v[0], v[1]) for k_, v in sorted(out.items())}

    def render(self, k_detail: int = 5) -> str:
        lines = [f"{self.n} labelled question(s) over the corpus", ""]
        lines.append(f"{'k':>4}  {'hit@k':>7}  {'recall@k':>9}")
        for k in self.ks:
            lines.append(f"{k:>4}  {self.hit_rate(k):>6.1%}  {self.recall(k):>8.1%}")
        lines.append("")
        lines.append(f"MRR                    {self.mrr:.3f}")
        pinned, agnostic = self.split()
        if pinned.n and agnostic.n:
            lines.append(
                f"  year-pinned  (n={pinned.n:>2}, year filter applied): "
                f"hit@{max(self.ks)} {pinned.hit_rate(max(self.ks)):.1%}, "
                f"MRR {pinned.mrr:.3f}")
            lines.append(
                f"  year-agnostic(n={agnostic.n:>2}, whole corpus):       "
                f"hit@{max(self.ks)} {agnostic.hit_rate(max(self.ks)):.1%}, "
                f"MRR {agnostic.mrr:.3f}")
        lines.append(f"mean top-document share of top-{max(self.ks)}   "
                     f"{self.top_doc_share:.1%}   (Audit R4 watch item)")

        lines.append(f"\nhit@{k_detail} by Item")
        for section, (hits, asked) in self.by_section(k_detail).items():
            lines.append(f"  {section:<10} {hits}/{asked}")

        if misses := self.misses(k_detail):
            lines.append(f"\nMISSED at k={k_detail} ({len(misses)})")
            for r in misses:
                gold = "; ".join(str(g) for g in r.question.gold)
                got = ", ".join(f"{c['ticker']} FY{c['fiscal_year']} "
                                f"{c.get('section_key') or c.get('section')}"
                                for c in r.retrieved[:3])
                lines.append(f"  {r.question.id}: {r.question.question}")
                lines.append(f"      wanted {gold}")
                lines.append(f"      got    {got}")
        return "\n".join(lines)


# --------------------------------------------------------------------------

def load_questions(path: str | Path | None = None) -> list[Question]:
    doc = yaml.safe_load(Path(path or QUESTIONS_PATH).read_text(encoding="utf-8"))
    questions: list[Question] = []
    for entry in doc["questions"]:
        gold = tuple(GoldTarget(
            ticker=g["ticker"],
            fiscal_year=(ANY_YEAR if str(g["fiscal_year"]).lower() == ANY_YEAR
                         else int(g["fiscal_year"])),
            section_key=g["section_key"])
            for g in entry["gold"])
        questions.append(Question(
            id=entry["id"], question=entry["question"], gold=gold,
            must_match=entry.get("must_match"), ticker=entry.get("ticker"),
            year=entry.get("year"), note=entry.get("note", "")))
    return questions


_model = None


def _embed(texts: list[str]):
    """One batched encode for the whole question set — the slow part on CPU."""
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer

        from src.config import EMBEDDING_MODEL
        _model = SentenceTransformer(EMBEDDING_MODEL)
    return _model.encode(texts, normalize_embeddings=True)


_COLS = ("chunk_id", "page", "end_page", "section", "ticker", "fiscal_year",
         "doc_type", "content", "format", "section_key", "start_char", "distance")


def run_eval(questions: list[Question] | None = None, *, k: int = 10,
             ks: tuple[int, ...] = DEFAULT_KS) -> EvalReport:
    """Retrieve for every question and score against the gold labels.

    Retrieval goes through rag_chat's own SQL so the harness measures the
    retriever the pipeline actually uses, not a reimplementation of it.
    """
    questions = questions or load_questions()
    vectors = _embed([q.question for q in questions])

    results: list[QuestionResult] = []
    with get_conn() as conn:
        for question, qvec in zip(questions, vectors):
            rows = conn.execute(RETRIEVAL_SQL, {
                "qvec": qvec, "ticker": question.ticker,
                "year": question.year, "k": max(k, max(ks))}).fetchall()
            retrieved = [dict(zip(_COLS, r)) for r in rows]
            ranks = [i + 1 for i, c in enumerate(retrieved) if question.relevant(c)]
            results.append(QuestionResult(question=question, ranks=ranks,
                                          retrieved=retrieved))
    return EvalReport(results=results, ks=ks)
