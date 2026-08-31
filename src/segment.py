"""Module 15 — segmentation router: one command, two segmenters.

    documents.format = 'pdf'   -> src.sections        (HK annual reports, page anchors)
    documents.format = 'html'  -> src.edgar.sections_us (10-K Items, char offsets)

The two never merge and never fall back to one another. A 10-K that fails to
anchor on its Items raises: silently handing it to the heuristic segmenter would
produce plausible-looking sections that are wrong, which is the failure mode this
pipeline exists to prevent.

Both writers populate `section_type` from the same vocabulary, so rag_chat,
alerts and app keep working across both corpora; the US path additionally writes
`section_key` ('item_1a') for Item-precise retrieval.

CLI:  python -m src.segment --doc-id 43 --apply
      python -m src.segment --all-html --apply
"""
from src.db import get_conn

INSERT_SECTION = """
INSERT INTO sections (doc_id, section_type, section_key, segmenter,
                      start_char, end_char, text)
VALUES (%s, %s, %s, 'item_anchor_us', %s, %s, %s)
"""


def segment_html(doc_id: int, *, apply_to_chunks: bool = False) -> list:
    """Item-anchor a US filing and replace its sections rows."""
    from src.edgar.sections_us import segment_filing

    with get_conn() as conn:
        row = conn.execute(
            "SELECT accession FROM documents WHERE doc_id = %s", (doc_id,)).fetchone()
        if not row or not row[0]:
            raise ValueError(f"doc_id {doc_id} has no accession — not a US filing")
        accession = row[0]

    text, sections = segment_filing(accession)

    with get_conn() as conn:
        conn.execute("DELETE FROM sections WHERE doc_id = %s", (doc_id,))
        with conn.cursor() as cur:
            cur.executemany(INSERT_SECTION, [
                (doc_id, s.section_type, s.section_key, s.start_char, s.end_char,
                 text[s.start_char:s.end_char]) for s in sections])
        if apply_to_chunks:
            conn.execute(
                """UPDATE chunks c SET section_id = s.section_id
                   FROM sections s
                   WHERE s.doc_id = c.doc_id AND c.doc_id = %s
                     AND c.start_char >= s.start_char AND c.start_char < s.end_char""",
                (doc_id,))
    return sections


def segment(doc_id: int, *, apply_to_chunks: bool = False):
    """Dispatch on document format."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT format FROM documents WHERE doc_id = %s", (doc_id,)).fetchone()
    if not row:
        raise ValueError(f"doc_id {doc_id} does not exist")

    if row[0] == "html":
        return segment_html(doc_id, apply_to_chunks=apply_to_chunks)

    from src.sections import segment as segment_pdf
    return segment_pdf(doc_id, apply_to_chunks=apply_to_chunks)


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--doc-id", type=int)
    ap.add_argument("--all-html", action="store_true")
    ap.add_argument("--apply", action="store_true", help="also tag chunks")
    a = ap.parse_args()

    if a.all_html:
        with get_conn() as conn:
            targets = [r[0] for r in conn.execute(
                "SELECT doc_id FROM documents WHERE format = 'html' ORDER BY doc_id")]
    else:
        targets = [a.doc_id]

    for doc_id in targets:
        sections = segment(doc_id, apply_to_chunks=a.apply)
        # US sections are Section objects; the PDF segmenter returns (type, a, b) tuples
        keys = [s.section_key if hasattr(s, "section_key") else s[0] for s in sections]
        print(f"  doc_id {doc_id:<4} {len(sections):>2} sections  {', '.join(keys[:8])}...")
