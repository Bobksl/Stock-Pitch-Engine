"""Module 2 — Section segmentation (heading heuristics, rules not ML).

A page's leading lines are scanned for near-exact section-heading matches.
Rules that matter for real HK/UK annual reports:
- page headers repeat the current section name on every page, so a new section
  opens only when the detected TYPE differs from the currently open one;
- nav-bar lines (e.g. HSBC's "Strategic report ESG review Financial review ...")
  contain several section names at once — any line matching >1 type is rejected;
- headings are short; a line much longer than the matched pattern is body text.

Sections span [start_page, next_start - 1]. Pages before the first heading are 'Other'.

CLI:  python -m src.sections.hk --doc-id 1   (add --apply to also tag chunks)
"""
import re

from src.db import get_conn

SECTION_PATTERNS: dict[str, list[re.Pattern]] = {
    "MD&A": [
        re.compile(r"management[’']?s? discussion and analysis", re.I),
        re.compile(r"^(business|operations?|financial) review$", re.I),
        re.compile(r"^strategic report$", re.I),
    ],
    "Risk Factors": [
        re.compile(r"^risk factors?$", re.I),
        re.compile(r"^(principal|main|key|emerging) risks?( and uncertainties)?$", re.I),
        re.compile(r"^risk (review|management( report)?)$", re.I),
    ],
    "Financial Statements": [
        re.compile(r"^independent auditor[’']?s? report", re.I),
        re.compile(r"^consolidated (income statement|statement of|balance sheet|financial statements)", re.I),
        re.compile(r"^notes (to|on) the (consolidated )?financial statements", re.I),
        re.compile(r"^financial statements$", re.I),
    ],
    "Corporate Governance": [
        re.compile(r"^corporate governance( report)?$", re.I),
        re.compile(r"^(report of the directors|directors[’']? report)$", re.I),
        re.compile(r"^environmental, social and governance", re.I),
    ],
}

MAX_HEADING_LEN = 70   # headings are short
LEAD_LINES = 8         # only scan the top of each page
MIN_SECTION_PAGES = 3  # shorter runs are almost always repeated page-headers (OCR docs), not real sections


def classify_page(text: str) -> str | None:
    """Return the section type this page STARTS, or None."""
    lines = [ln.strip() for ln in (text or "").split("\n") if ln.strip()][:LEAD_LINES]
    for line in lines:
        if len(line) > MAX_HEADING_LEN:
            continue
        matched = {
            stype
            for stype, pats in SECTION_PATTERNS.items()
            if any(p.search(line) for p in pats)
        }
        if len(matched) == 1:  # multi-type line = nav bar, reject
            return matched.pop()
    return None


def segment(doc_id: int, apply_to_chunks: bool = False) -> list[tuple]:
    """Detect sections, replace this doc's sections rows, optionally tag chunks."""
    with get_conn() as conn:
        pages = conn.execute(
            "SELECT page_num, raw_text FROM pages WHERE doc_id = %s ORDER BY page_num", (doc_id,)
        ).fetchall()
        if not pages:
            raise SystemExit(f"doc_id {doc_id} has no pages")

        # (start_page, type): open a new section only when the type CHANGES
        starts: list[tuple[int, str]] = [(pages[0][0], "Other")]
        for page_num, text in pages:
            stype = classify_page(text)
            if stype and stype != starts[-1][1]:
                if starts[-1][0] == page_num:  # first page immediately classified
                    starts[-1] = (page_num, stype)
                else:
                    starts.append((page_num, stype))

        last_page = pages[-1][0]
        spans = [
            (stype, start, (starts[i + 1][0] - 1) if i + 1 < len(starts) else last_page)
            for i, (start, stype) in enumerate(starts)
        ]

        # Hysteresis: absorb sub-MIN_SECTION_PAGES runs into the previous section, then
        # re-merge adjacent same-type spans. Kills header-line flip-flop on OCR'd docs.
        merged: list[list] = []
        for stype, a, b in spans:
            if merged and (b - a + 1) < MIN_SECTION_PAGES:
                merged[-1][2] = b
            elif merged and merged[-1][0] == stype and merged[-1][2] + 1 == a:
                merged[-1][2] = b
            else:
                merged.append([stype, a, b])
        spans = [tuple(m) for m in merged]

        conn.execute("DELETE FROM sections WHERE doc_id = %s", (doc_id,))
        with conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO sections (doc_id, section_type, start_page, end_page) VALUES (%s, %s, %s, %s)",
                [(doc_id, s, a, b) for s, a, b in spans],
            )
        if apply_to_chunks:
            conn.execute(
                """UPDATE chunks c SET section_id = s.section_id
                   FROM sections s
                   WHERE s.doc_id = c.doc_id AND c.doc_id = %s
                     AND c.page BETWEEN s.start_page AND s.end_page""",
                (doc_id,),
            )
    return spans


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--doc-id", type=int, required=True)
    ap.add_argument("--apply", action="store_true", help="also tag existing chunks with section_id")
    a = ap.parse_args()
    for stype, start, end in segment(a.doc_id, apply_to_chunks=a.apply):
        print(f"  p.{start:>3}-{end:<3}  {stype}")
