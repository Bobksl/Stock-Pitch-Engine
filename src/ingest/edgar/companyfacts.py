"""Module 9 — SEC companyfacts: the reconciliation oracle.

companyfacts publishes NON-DIMENSIONAL facts only: consolidated totals, no
segment or geography members. That is precisely why it cannot be the primary
source (framework 1.3 needs segment operating profit), and precisely why it is
a good oracle — it is SEC's own independent rendering of the same filings, so
agreeing with it to the cent is real evidence the instance parser is correct.

Endpoint: data.sec.gov/api/xbrl/companyfacts/CIK##########.json
Shape:    facts.{taxonomy}.{tag}.units.{unit}[] -> {start?, end, val, accn, fy, fp, form, filed}

CLI:  python -m src.ingest.edgar.companyfacts 789019 --tag Revenues
"""
from datetime import date
from typing import Iterator

from src.ingest.edgar.client import fetch_json

COMPANYFACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"


def fetch_companyfacts(cik: int, *, force: bool = False) -> dict:
    return fetch_json(COMPANYFACTS_URL.format(cik=cik), force=force)


def iter_companyfacts(cik: int, *, force: bool = False) -> Iterator[dict]:
    """Flatten companyfacts into fact rows.

    A period with no `start` is an instant (balance-sheet) fact — the same
    distinction the instance parser makes from xbrli:instant.
    """
    doc = fetch_companyfacts(cik, force=force)
    for taxonomy, tags in doc.get("facts", {}).items():
        for tag, body in tags.items():
            for unit, entries in body.get("units", {}).items():
                for e in entries:
                    start = e.get("start")
                    yield {
                        "taxonomy": taxonomy, "tag": tag, "unit": unit,
                        "period_type": "duration" if start else "instant",
                        "start": date.fromisoformat(start) if start else None,
                        "end": date.fromisoformat(e["end"]),
                        "val": e["val"], "accn": e["accn"],
                        "fy": e.get("fy"), "fp": e.get("fp"),
                        "form": e.get("form"),
                        "filed": date.fromisoformat(e["filed"]),
                    }


def index_by_key(cik: int, *, force: bool = False) -> dict[tuple, list[dict]]:
    """Facts keyed by (accession, taxonomy, tag, unit, start, end) for lookup."""
    index: dict[tuple, list[dict]] = {}
    for r in iter_companyfacts(cik, force=force):
        key = (r["accn"], r["taxonomy"], r["tag"], r["unit"], r["start"], r["end"])
        index.setdefault(key, []).append(r)
    return index


if __name__ == "__main__":
    import argparse
    from collections import Counter

    ap = argparse.ArgumentParser()
    ap.add_argument("cik", type=int)
    ap.add_argument("--tag")
    a = ap.parse_args()

    rows = list(iter_companyfacts(a.cik))
    print(f"{len(rows):,} facts   taxonomies: {dict(Counter(r['taxonomy'] for r in rows))}")
    print(f"dimensional facts published by this API: 0 (by design — consolidated only)")

    if a.tag:
        seen = {(r["start"], r["end"]): r for r in rows
                if r["tag"] == a.tag and r["form"] == "10-K"}
        for (s, e), r in sorted(seen.items(), key=lambda kv: kv[0][1], reverse=True)[:8]:
            print(f"  {s} -> {e}  {r['val']:>20,}  {r['unit']:<10} accn={r['accn']}")
