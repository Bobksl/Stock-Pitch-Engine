"""Day-2 retrieval QA: 10 hand-written questions across the 3-filing corpus.

Retrieval-only (no LLM cost): prints top-5 chunks per question with citation
metadata and a text preview, for manual relevance judgement.

Run:  python scripts/retrieval_qa.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.retrieval.chat import retrieve

QUESTIONS: list[tuple[str, str | None]] = [
    # (question, ticker filter or None)
    ("What were Tencent's main revenue drivers in 2025?", "0700.HK"),
    ("How much did Tencent spend on share repurchases in 2025?", "0700.HK"),
    ("What dividend did Tencent declare for 2025?", "0700.HK"),
    ("How did Bilibili's advertising business perform in 2025?", "9626.HK"),
    ("What was Bilibili's gross profit margin trend in 2025?", "9626.HK"),
    ("What was HSBC's profit before tax in 2025?", "0005.HK"),
    ("What are HSBC's main credit risk exposures?", "0005.HK"),
    ("What is HSBC's CET1 capital ratio?", "0005.HK"),
    ("Compare gaming revenue growth at Tencent and Bilibili in 2025.", None),
    ("Which companies discuss AI investments in their 2025 filings?", None),
]


def main() -> None:
    for i, (q, ticker) in enumerate(QUESTIONS, 1):
        print(f"\nQ{i} [{ticker or 'ALL'}] {q}")
        for c in retrieve(q, ticker=ticker, k=5):
            pages = f"p.{c['page']}" if c["end_page"] == c["page"] else f"p.{c['page']}-{c['end_page']}"
            preview = " ".join(c["content"].split())[:90]
            print(f"  d={c['distance']:.3f} {c['ticker']} | {c['section'][:20]:<20} | {pages:<10} | {preview}")


if __name__ == "__main__":
    main()
