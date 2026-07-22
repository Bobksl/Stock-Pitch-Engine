"""Module 3 — Chunking + local BGE-M3 embedding into pgvector.

Day-1 walking skeleton: page-aware token-window chunking (~CHUNK_TOKENS tokens,
CHUNK_OVERLAP_TOKENS overlap, tiktoken counts). Each chunk records the page its
first token came from — that page is the citation anchor. Section-aware chunking
lands with Module 2 (Day 2); section_id stays NULL until then.

CLI:  python -m src.chunk_embed --doc-id 1
"""
import tiktoken

from src.config import CHUNK_OVERLAP_TOKENS, CHUNK_TOKENS, EMBEDDING_MODEL
from src.db import get_conn

_encoder = tiktoken.get_encoding("cl100k_base")  # sizing only; not the model tokenizer


def get_embedder():
    """Lazy-load sentence-transformers model (first call downloads ~2.3 GB)."""
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(EMBEDDING_MODEL)


def build_chunks(pages: list[tuple[int, str]]) -> list[dict]:
    """Token stream with per-token page attribution -> overlapping windows."""
    stream: list[tuple[int, int]] = []  # (token_id, page_num)
    for page_num, text in pages:
        if text:
            stream.extend((tok, page_num) for tok in _encoder.encode(text))
        # page boundary -> newline token keeps pages from fusing mid-sentence
        stream.extend((tok, page_num) for tok in _encoder.encode("\n"))

    chunks, start, step = [], 0, CHUNK_TOKENS - CHUNK_OVERLAP_TOKENS
    while start < len(stream):
        window = stream[start : start + CHUNK_TOKENS]
        text = _encoder.decode([t for t, _ in window]).strip()
        if text:
            chunks.append({
                "page": window[0][1],
                "end_page": window[-1][1],  # facts near boundaries need the range, not just the first page
                "content": text,
                "token_count": len(window),
            })
        start += step
    return chunks


def chunk_and_embed(doc_id: int) -> int:
    with get_conn() as conn:
        pages = conn.execute(
            "SELECT page_num, raw_text FROM pages WHERE doc_id = %s ORDER BY page_num", (doc_id,)
        ).fetchall()
    if not pages:
        raise SystemExit(f"doc_id {doc_id} has no pages — run src.ingest first")

    chunks = build_chunks(pages)
    print(f"doc_id={doc_id}: {len(chunks)} chunks from {len(pages)} pages; embedding with {EMBEDDING_MODEL}...")

    model = get_embedder()
    embeddings = model.encode(
        [c["content"] for c in chunks], batch_size=8, normalize_embeddings=True, show_progress_bar=True
    )

    with get_conn() as conn:
        conn.execute("DELETE FROM chunks WHERE doc_id = %s", (doc_id,))  # rerun safety
        with conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO chunks (doc_id, page, end_page, content, token_count, embedding)"
                " VALUES (%s, %s, %s, %s, %s, %s)",
                [(doc_id, c["page"], c["end_page"], c["content"], c["token_count"], emb)
                 for c, emb in zip(chunks, embeddings)],
            )
    print(f"stored {len(chunks)} embedded chunks")
    return len(chunks)


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--doc-id", type=int, required=True)
    chunk_and_embed(ap.parse_args().doc_id)
