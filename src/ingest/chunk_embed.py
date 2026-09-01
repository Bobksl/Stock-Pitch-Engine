"""Module 3 — Chunking + local BGE-M3 embedding into pgvector.

Two chunkers, chosen by documents.format:

  'pdf'   page-attributed token windows. Each chunk records the page its first
          token came from — that page is the citation anchor. (Unchanged: this
          is the HK path and its output must stay byte-identical.)

  'html'  paragraph-packed windows over the extracted filing text, recording
          character offsets. A 10-K has no pages, so the offset is the anchor,
          and packing whole paragraphs keeps table rows and prose intact instead
          of slicing mid-sentence at an arbitrary token count.

CLI:  python -m src.ingest.chunk_embed --doc-id 1
      python -m src.ingest.chunk_embed --all-html
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


# ---------------------------------------------------------------------------
# HTML path: character-anchored
# ---------------------------------------------------------------------------

def _blocks(text: str) -> list[tuple[int, int]]:
    """Paragraph spans (start, end), splitting oversized ones on line breaks.

    to_text() normalises runs of blank lines to exactly one, so paragraph
    offsets follow from cumulative lengths — no searching, no drift.
    """
    spans, pos = [], 0
    for para in text.split("\n\n"):
        end = pos + len(para)
        if para.strip():
            if len(_encoder.encode(para)) <= CHUNK_TOKENS:
                spans.append((pos, end))
            else:                                  # a long table: fall back to lines
                line_pos = pos
                for line in para.split("\n"):
                    if line.strip():
                        spans.append((line_pos, line_pos + len(line)))
                    line_pos += len(line) + 1
        pos = end + 2                              # the "\n\n" separator
    return spans


def build_chunks_from_text(text: str) -> list[dict]:
    """Pack whole paragraphs into ~CHUNK_TOKENS windows with overlap."""
    spans = _blocks(text)
    sizes = [len(_encoder.encode(text[a:b])) for a, b in spans]

    chunks, i = [], 0
    while i < len(spans):
        total, j = 0, i
        while j < len(spans) and (total + sizes[j] <= CHUNK_TOKENS or j == i):
            total += sizes[j]
            j += 1

        start_char, end_char = spans[i][0], spans[j - 1][1]
        content = text[start_char:end_char].strip()
        if content:
            chunks.append({"start_char": start_char, "end_char": end_char,
                           "content": content, "token_count": total})
        if j >= len(spans):
            break

        # step back far enough to overlap ~CHUNK_OVERLAP_TOKENS
        back, overlap = j, 0
        while back > i + 1 and overlap < CHUNK_OVERLAP_TOKENS:
            back -= 1
            overlap += sizes[back]
        i = back
    return chunks


def _embed_and_store(doc_id: int, chunks: list[dict], columns: tuple[str, ...]) -> int:
    print(f"doc_id={doc_id}: {len(chunks)} chunks; embedding with {EMBEDDING_MODEL}...")
    model = get_embedder()
    embeddings = model.encode([c["content"] for c in chunks], batch_size=8,
                              normalize_embeddings=True, show_progress_bar=True)

    cols = ", ".join(("doc_id",) + columns + ("embedding",))
    placeholders = ", ".join(["%s"] * (len(columns) + 2))
    with get_conn() as conn:
        conn.execute("DELETE FROM chunks WHERE doc_id = %s", (doc_id,))  # rerun safety
        with conn.cursor() as cur:
            cur.executemany(
                f"INSERT INTO chunks ({cols}) VALUES ({placeholders})",
                [(doc_id, *(c[k] for k in columns), emb)
                 for c, emb in zip(chunks, embeddings)])
    print(f"stored {len(chunks)} embedded chunks")
    return len(chunks)


def chunk_and_embed(doc_id: int) -> int:
    """Dispatch on document format; HK PDFs keep the page-attributed path."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT format, accession FROM documents WHERE doc_id = %s", (doc_id,)).fetchone()
    if not row:
        raise SystemExit(f"doc_id {doc_id} does not exist")
    fmt, accession = row

    if fmt == "html":
        from src.ingest.edgar.html_text import cached_filing_text

        chunks = build_chunks_from_text(cached_filing_text(accession))
        return _embed_and_store(doc_id, chunks,
                                ("start_char", "end_char", "content", "token_count"))

    with get_conn() as conn:
        pages = conn.execute(
            "SELECT page_num, raw_text FROM pages WHERE doc_id = %s ORDER BY page_num",
            (doc_id,)).fetchall()
    if not pages:
        raise SystemExit(f"doc_id {doc_id} has no pages — run src.ingest.pdf first")
    return _embed_and_store(doc_id, build_chunks(pages),
                            ("page", "end_page", "content", "token_count"))


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--doc-id", type=int)
    ap.add_argument("--all-html", action="store_true")
    a = ap.parse_args()

    if a.all_html:
        with get_conn() as conn:
            targets = [r[0] for r in conn.execute(
                "SELECT doc_id FROM documents WHERE format = 'html' ORDER BY doc_id")]
    else:
        targets = [a.doc_id]

    for doc_id in targets:
        chunk_and_embed(doc_id)
