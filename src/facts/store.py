"""Module 8 — write parsed facts into the facts table.

Two writers, one table, distinguished by `source`:
  'instance'      — parsed from the filing itself; carries dimensions
  'companyfacts'  — SEC's own consolidated series; the reconciliation oracle

Both are idempotent: re-running upserts on the natural key
(cik, accession, taxonomy, tag, unit, period, segments, source), so a parser fix
followed by a re-run corrects values in place rather than duplicating them.

fy / fp come from the filer's own dei tags, never inferred from a report date.

CLI:  python -m src.facts.store 0000950170-24-087843
      python -m src.facts.store --all
"""
from decimal import Decimal

from psycopg.types.json import Jsonb

from src.db import get_conn
from src.ingest.edgar.ixbrl import XbrlFact, parse_cached_filing

UPSERT_FACT = """
INSERT INTO facts (cik, accession, doc_id, taxonomy, tag, unit, period_type,
                   period_start, period_end, fy, fp, form, filed_date, value,
                   decimals, segments, context_id, source)
VALUES (%(cik)s, %(accession)s, %(doc_id)s, %(taxonomy)s, %(tag)s, %(unit)s,
        %(period_type)s, %(period_start)s, %(period_end)s, %(fy)s, %(fp)s,
        %(form)s, %(filed_date)s, %(value)s, %(decimals)s, %(segments)s,
        %(context_id)s, %(source)s)
ON CONFLICT (cik, accession, taxonomy, tag, unit, period_start, period_end,
             segments_hash, source)
DO UPDATE SET value = EXCLUDED.value, decimals = EXCLUDED.decimals,
              context_id = EXCLUDED.context_id, doc_id = EXCLUDED.doc_id,
              fy = EXCLUDED.fy, fp = EXCLUDED.fp, ingested_at = now()
"""


def _row(f: XbrlFact, filing: dict, source: str) -> dict:
    return {
        "cik": filing["cik"], "accession": filing["accession"],
        "doc_id": filing["doc_id"], "taxonomy": f.taxonomy, "tag": f.tag,
        "unit": f.unit, "period_type": f.period_type,
        "period_start": f.period_start, "period_end": f.period_end,
        "fy": filing["fy"], "fp": filing["fp"], "form": filing["form"],
        "filed_date": filing["filed_date"], "value": f.value,
        "decimals": f.decimals, "segments": Jsonb(f.segments),
        "context_id": f.context_id, "source": source,
    }


def store_filing_facts(accession: str) -> dict:
    """Parse a fetched filing and load its facts. Returns a summary."""
    facts, dei = parse_cached_filing(accession)

    with get_conn() as conn:
        row = conn.execute(
            """SELECT cik, accession, doc_id, form, filed_date
               FROM filings WHERE accession = %s""", (accession,)).fetchone()
        if not row:
            raise ValueError(f"accession {accession} has not been fetched")
        filing = dict(zip(["cik", "accession", "doc_id", "form", "filed_date"], row))
        filing["fy"] = int(dei["DocumentFiscalYearFocus"]) if dei.get("DocumentFiscalYearFocus") else None
        filing["fp"] = dei.get("DocumentFiscalPeriodFocus")

        with conn.cursor() as cur:
            cur.executemany(UPSERT_FACT, [_row(f, filing, "instance") for f in facts])

        # The filer's own answer, recorded once it is known.
        conn.execute("UPDATE filings SET fy = %s, fp = %s, facts_loaded = TRUE "
                     "WHERE accession = %s", (filing["fy"], filing["fp"], accession))

    dimensional = sum(1 for f in facts if f.segments)
    return {"accession": accession, "facts": len(facts),
            "consolidated": len(facts) - dimensional, "dimensional": dimensional,
            "fy": filing["fy"], "fp": filing["fp"]}


def store_companyfacts(cik: int, *, force: bool = False) -> dict:
    """Load SEC's consolidated series for one filer (source='companyfacts')."""
    from src.ingest.edgar.companyfacts import iter_companyfacts

    with get_conn() as conn:
        rows = [{
            "cik": cik, "accession": r["accn"], "doc_id": None,
            "taxonomy": r["taxonomy"], "tag": r["tag"], "unit": r["unit"],
            "period_type": r["period_type"], "period_start": r["start"],
            "period_end": r["end"], "fy": r["fy"], "fp": r["fp"], "form": r["form"],
            "filed_date": r["filed"], "value": Decimal(str(r["val"])),
            "decimals": None, "segments": Jsonb({}), "context_id": None,
            "source": "companyfacts",
        } for r in iter_companyfacts(cik, force=force)]

        with conn.cursor() as cur:
            cur.executemany(UPSERT_FACT, rows)

    return {"cik": cik, "facts": len(rows)}


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("accession", nargs="?")
    ap.add_argument("--all", action="store_true", help="every fetched filing")
    a = ap.parse_args()

    if a.all:
        with get_conn() as conn:
            targets = [r[0] for r in conn.execute(
                "SELECT accession FROM filings ORDER BY cik, period_end DESC")]
    else:
        targets = [a.accession]

    for acc in targets:
        s = store_filing_facts(acc)
        print(f"  {s['accession']}  FY{s['fy']} {s['fp']}  {s['facts']:>6,} facts "
              f"({s['consolidated']:,} consolidated / {s['dimensional']:,} dimensional)")
