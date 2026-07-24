"""Module 4 — RAG chat loop (raw Python + SQL, no framework).

embed question (same local embedding model) -> metadata-filtered HNSW cosine top-k SQL
-> grounding prompt with [ticker year type | section | p.N] tags per chunk
-> configured LLM -> answer + structured citations.

CLI:  python -m src.rag_chat "What were the main revenue drivers?" [--ticker 0700.HK] [--year 2025] [-k 8]
"""
from src import llm
from src.db import get_conn

SYSTEM_PROMPT = (
    "You are a financial-filings research assistant for an equity fund. Rules:\n"
    "1. Answer ONLY from the provided context chunks — never use outside knowledge, "
    "even for well-known facts about these companies.\n"
    "2. Cite every claim inline with the EXACT bracketed tag of the supporting chunk, "
    "e.g. [0700.HK 2025 annual | MD&A | p.7-8]. Do not invent or alter tags.\n"
    "3. Quote figures exactly as written in the context (units, currency, precision).\n"
    "4. If chunks conflict, present both figures with their tags and note the conflict.\n"
    "5. If the context does not contain the answer, reply 'Not found in the provided "
    "filings.' — do not speculate. Partial answers are fine if labelled as partial.\n"
    "6. Some context comes from OCR and may contain garbled fragments; ignore gibberish "
    "and never quote it.\n"
    "7. Be concise: direct answer first, supporting detail after."
)

RETRIEVAL_SQL = """
SELECT c.chunk_id, c.page, COALESCE(c.end_page, c.page) AS end_page,
       COALESCE(s.section_type, 'n/a') AS section,
       d.ticker, d.fiscal_year, d.doc_type, c.content,
       c.embedding <=> %(qvec)s AS distance
FROM chunks c
JOIN documents d ON d.doc_id = c.doc_id
LEFT JOIN sections s ON s.section_id = c.section_id
WHERE (%(ticker)s::text IS NULL OR d.ticker = %(ticker)s)
  AND (%(year)s::int    IS NULL OR d.fiscal_year = %(year)s)
ORDER BY c.embedding <=> %(qvec)s
LIMIT %(k)s
"""

_model = None


def _embed_question(question: str):
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer

        from src.config import EMBEDDING_MODEL

        _model = SentenceTransformer(EMBEDDING_MODEL)
    return _model.encode([question], normalize_embeddings=True)[0]


def retrieve(question: str, ticker: str | None = None, year: int | None = None, k: int = 8) -> list[dict]:
    qvec = _embed_question(question)
    with get_conn() as conn:
        rows = conn.execute(RETRIEVAL_SQL, {"qvec": qvec, "ticker": ticker, "year": year, "k": k}).fetchall()
    cols = ("chunk_id", "page", "end_page", "section", "ticker", "fiscal_year", "doc_type", "content", "distance")
    return [dict(zip(cols, r)) for r in rows]


def _pages(c: dict) -> str:
    return f"p.{c['page']}" if c["end_page"] == c["page"] else f"p.{c['page']}-{c['end_page']}"


def _tag(c: dict) -> str:
    return f"[{c['ticker']} {c['fiscal_year']} {c['doc_type']} | {c['section']} | {_pages(c)}]"


def answer(question: str, ticker: str | None = None, year: int | None = None, k: int = 8) -> dict:
    chunks = retrieve(question, ticker, year, k)
    if not chunks:
        return {"answer": "No chunks retrieved — is the corpus embedded?", "citations": []}

    context = "\n\n".join(f"{_tag(c)}\n{c['content']}" for c in chunks)
    resp = llm.complete(
        [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"Context chunks:\n\n{context}\n\nQuestion: {question}"},
        ],
        temperature=0.2,
    )
    citations = [
        {k_: c[k_] for k_ in ("ticker", "fiscal_year", "doc_type", "section", "page", "end_page",
                              "distance", "content")}
        for c in chunks
    ]
    return {"answer": resp.choices[0].message.content, "citations": citations, "usage": str(resp.usage)}


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("question")
    ap.add_argument("--ticker")
    ap.add_argument("--year", type=int)
    ap.add_argument("-k", type=int, default=8)
    a = ap.parse_args()

    result = answer(a.question, a.ticker, a.year, a.k)
    print("\n=== ANSWER ===\n")
    print(result["answer"])
    print("\n=== RETRIEVED SOURCES ===")
    for c in result["citations"]:
        pages = f"p.{c['page']}" if c["end_page"] == c["page"] else f"p.{c['page']}-{c['end_page']}"
        print(f"  {c['ticker']} {c['fiscal_year']} {c['doc_type']} | {c['section']} | {pages}"
              f" | distance={c['distance']:.4f}")
