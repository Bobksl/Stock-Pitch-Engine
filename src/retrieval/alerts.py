"""Module 5 — Section summaries + YoY change alerts.

summarize_sections(doc_id): for every detected section (except 'Other'), summarize its
page text with the configured LLM -> summaries table; also writes one 'new_filing' alert.

detect_changes(ticker, year_a, year_b): for each section TYPE present in both years,
compare the two years' summaries -> 'change_detected' alerts rows anchored to the
newer doc's section (doc_id / section_id / page_ref all set, so every alert links back
to its source).

CLI:
  python -m src.retrieval.alerts summarize --doc-id 1
  python -m src.retrieval.alerts diff --ticker 0700.HK --from-year 2024 --to-year 2025
"""
from src import llm
from src.config import LLM_MODEL, LLM_SECTION_TEXT_CAP
from src.db import get_conn

SUMMARY_PROMPT = (
    "Summarize the following filing section in 3-5 bullet points, focused on: revenue/margin "
    "trends, capex and investment plans, and stated risks. Quote key figures exactly as written. "
    "Do not add outside information.\n\nSection: {section_type} | {ticker} | FY{year}\n\n{text}"
)

CHANGE_PROMPT = (
    "Below are two summaries of the SAME section of the SAME company's annual report, one year "
    "apart. List only MATERIAL changes in direction or magnitude (e.g. growth acceleration or "
    "reversal, a new risk appearing, a risk disappearing, margin trend change, new strategic "
    "priority). Quote figures where available. If nothing material changed, reply exactly "
    "'NO MATERIAL CHANGES'.\n\n"
    "Company: {ticker} | Section: {section_type}\n\n"
    "=== Summary FY{year_a} (prior) ===\n{sum_a}\n\n=== Summary FY{year_b} (current) ===\n{sum_b}"
)

MIN_SECTION_CHARS = 500     # skip near-empty sections


def _chat(prompt: str) -> str:
    return llm.chat([{"role": "user", "content": prompt}], temperature=0.3)


def _section_text(conn, doc_id: int, start_page: int, end_page: int) -> str:
    rows = conn.execute(
        "SELECT raw_text FROM pages WHERE doc_id = %s AND page_num BETWEEN %s AND %s ORDER BY page_num",
        (doc_id, start_page, end_page),
    ).fetchall()
    return "\n".join(r[0] or "" for r in rows)[:LLM_SECTION_TEXT_CAP]


def summarize_sections(doc_id: int) -> int:
    """Summarize every real section of a doc. Idempotent per doc. Returns #summaries written."""
    with get_conn() as conn:
        meta = conn.execute(
            "SELECT ticker, fiscal_year, doc_type FROM documents WHERE doc_id = %s", (doc_id,)
        ).fetchone()
        if not meta:
            raise SystemExit(f"doc_id {doc_id} not found")
        ticker, year, doc_type = meta
        sections = conn.execute(
            """SELECT section_id, section_type, start_page, end_page FROM sections
               WHERE doc_id = %s AND section_type <> 'Other' ORDER BY start_page""",
            (doc_id,),
        ).fetchall()
        conn.execute("DELETE FROM summaries WHERE doc_id = %s", (doc_id,))

        written = 0
        for section_id, stype, a, b in sections:
            text = _section_text(conn, doc_id, a, b)
            if len(text) < MIN_SECTION_CHARS:
                continue
            summary = _chat(SUMMARY_PROMPT.format(section_type=stype, ticker=ticker, year=year, text=text))
            conn.execute(
                "INSERT INTO summaries (doc_id, section_id, summary_text, model) VALUES (%s, %s, %s, %s)",
                (doc_id, section_id, summary, LLM_MODEL),
            )
            written += 1
            print(f"  summarized {ticker} FY{year} {stype} p.{a}-{b} ({len(text):,} chars)")

        conn.execute(
            """INSERT INTO alerts (doc_id, alert_type, alert_text, page_ref)
               VALUES (%s, 'new_filing', %s, 1)""",
            (doc_id, f"New filing ingested and summarized: {ticker} FY{year} {doc_type} report "
                     f"({written} section summaries)."),
        )
    return written


def detect_changes(ticker: str, year_a: int, year_b: int) -> int:
    """Compare per-section-type summaries across two years -> alerts on the newer doc."""
    with get_conn() as conn:
        def type_summaries(year: int) -> dict:
            rows = conn.execute(
                """SELECT s.section_type, MIN(s.section_id), MIN(s.start_page),
                          string_agg(su.summary_text, E'\n---\n' ORDER BY s.start_page)
                   FROM summaries su
                   JOIN sections s USING (section_id)
                   JOIN documents d ON d.doc_id = su.doc_id
                   WHERE d.ticker = %s AND d.fiscal_year = %s
                   GROUP BY s.section_type""",
                (ticker, year),
            ).fetchall()
            return {r[0]: {"section_id": r[1], "start_page": r[2], "summary": r[3]} for r in rows}

        prior, current = type_summaries(year_a), type_summaries(year_b)
        cur_doc = conn.execute(
            "SELECT doc_id FROM documents WHERE ticker = %s AND fiscal_year = %s", (ticker, year_b)
        ).fetchone()
        if not cur_doc:
            raise SystemExit(f"no {ticker} FY{year_b} document")
        cur_doc = cur_doc[0]

        conn.execute(
            "DELETE FROM alerts WHERE doc_id = %s AND alert_type = 'change_detected'", (cur_doc,)
        )
        written = 0
        for stype in sorted(set(prior) & set(current)):
            verdict = _chat(CHANGE_PROMPT.format(
                ticker=ticker, section_type=stype, year_a=year_a, year_b=year_b,
                sum_a=prior[stype]["summary"], sum_b=current[stype]["summary"],
            ))
            print(f"  {ticker} {stype}: {'no material changes' if verdict.upper().startswith('NO MATERIAL') else 'CHANGES DETECTED'}")
            if verdict.upper().startswith("NO MATERIAL"):
                continue
            conn.execute(
                """INSERT INTO alerts (doc_id, section_id, alert_type, alert_text, page_ref)
                   VALUES (%s, %s, 'change_detected', %s, %s)""",
                (cur_doc, current[stype]["section_id"],
                 f"[{ticker} {stype} | FY{year_a} vs FY{year_b}]\n{verdict}",
                 current[stype]["start_page"]),
            )
            written += 1
    return written


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    s1 = sub.add_parser("summarize")
    s1.add_argument("--doc-id", type=int, required=True)
    s2 = sub.add_parser("diff")
    s2.add_argument("--ticker", required=True)
    s2.add_argument("--from-year", type=int, required=True)
    s2.add_argument("--to-year", type=int, required=True)
    a = ap.parse_args()

    if a.cmd == "summarize":
        print(f"wrote {summarize_sections(a.doc_id)} summaries")
    else:
        print(f"wrote {detect_changes(a.ticker, a.from_year, a.to_year)} change alerts")
