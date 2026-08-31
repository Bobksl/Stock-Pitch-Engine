"""Module 6 — fetch a filing and register it.

Downloads the primary document (which for a post-2019 filing IS the inline-XBRL
instance: one fetch serves both the narrative segmenter and the facts parser)
plus FilingSummary.xml, then writes three rows:

  companies  — filer identity, keyed by ticker, carrying the CIK
  documents  — the narrative registry the RAG side already uses (format='html')
  filings    — EDGAR provenance: accession, URLs, cached path, sha256

Idempotent: re-running upserts by ticker / accession and re-uses the HTTP cache,
so a repeated run costs no requests and produces no duplicate rows.

CLI:  python -m src.edgar.fetch MSFT --years 5
"""
from src.db import get_conn
from src.edgar import client
from src.edgar.discover import Filing, company_meta, list_filings, ticker_to_cik

UPSERT_COMPANY = """
INSERT INTO companies (ticker, company_name, sector, cik, country, sic, fiscal_year_end)
VALUES (%(ticker)s, %(name)s, %(sector)s, %(cik)s, 'US', %(sic)s, %(fye)s)
ON CONFLICT (ticker) DO UPDATE SET
    company_name = EXCLUDED.company_name, sector = EXCLUDED.sector,
    cik = EXCLUDED.cik, country = 'US', sic = EXCLUDED.sic,
    fiscal_year_end = EXCLUDED.fiscal_year_end
"""

UPSERT_DOCUMENT = """
INSERT INTO documents (ticker, fiscal_year, doc_type, source_path, is_scanned,
                       cik, accession, format, form_type, period_end, filed_date,
                       source_url, sha256)
VALUES (%(ticker)s, %(fiscal_year)s, %(form)s, %(source_path)s, FALSE,
        %(cik)s, %(accession)s, 'html', %(form)s, %(period_end)s, %(filed_date)s,
        %(source_url)s, %(sha256)s)
ON CONFLICT (accession) WHERE accession IS NOT NULL DO UPDATE SET
    source_path = EXCLUDED.source_path, sha256 = EXCLUDED.sha256,
    fiscal_year = EXCLUDED.fiscal_year, period_end = EXCLUDED.period_end,
    filed_date = EXCLUDED.filed_date, source_url = EXCLUDED.source_url
RETURNING doc_id
"""

UPSERT_FILING = """
INSERT INTO filings (accession, cik, form, period_end, filed_date, primary_doc,
                     primary_url, cached_path, sha256, is_ixbrl, doc_id)
VALUES (%(accession)s, %(cik)s, %(form)s, %(period_end)s, %(filed_date)s,
        %(primary_doc)s, %(primary_url)s, %(cached_path)s, %(sha256)s,
        %(is_ixbrl)s, %(doc_id)s)
ON CONFLICT (accession) DO UPDATE SET
    cached_path = EXCLUDED.cached_path, sha256 = EXCLUDED.sha256,
    primary_url = EXCLUDED.primary_url, doc_id = EXCLUDED.doc_id
"""


def register_company(ticker: str, cik: int) -> dict:
    meta = company_meta(cik)
    with get_conn() as conn:
        conn.execute(UPSERT_COMPANY, {
            "ticker": ticker.upper(), "name": meta["name"],
            "sector": meta["sic_description"], "cik": cik,
            "sic": meta["sic"], "fye": meta["fiscal_year_end"],
        })
    return meta


def fetch_filing(f: Filing, ticker: str, *, force: bool = False) -> dict:
    """Download + register one filing. Returns a summary dict for reporting."""
    body = client.fetch(f.primary_url, force=force)
    meta = client.cache_meta(f.primary_url)

    # Cached for the facts parser (R-file → statement map); absent on old filings.
    try:
        client.fetch(f.filing_summary_url, force=force)
        has_summary = True
    except client.EdgarError:
        has_summary = False

    params = {
        "ticker": ticker.upper(), "cik": f.cik, "accession": f.accession,
        "form": f.form, "period_end": f.period_end, "filed_date": f.filed_date,
        "fiscal_year": f.period_end.year if f.period_end else None,
        "source_path": str(client.cache_path(f.primary_url)),
        "source_url": f.primary_url, "sha256": meta["sha256"],
    }
    with get_conn() as conn:
        doc_id = conn.execute(UPSERT_DOCUMENT, params).fetchone()[0]
        conn.execute(UPSERT_FILING, {
            **params, "primary_doc": f.primary_doc, "primary_url": f.primary_url,
            "cached_path": params["source_path"], "is_ixbrl": f.is_ixbrl,
            "doc_id": doc_id,
        })

    return {"accession": f.accession, "doc_id": doc_id, "bytes": len(body),
            "period_end": f.period_end, "filed_date": f.filed_date,
            "is_ixbrl": f.is_ixbrl, "has_summary": has_summary}


def fetch_company(ticker: str, *, forms: tuple[str, ...] = ("10-K",),
                  years: int = 5, force: bool = False) -> list[dict]:
    """Resolve a ticker and fetch its most recent filings of the given forms."""
    cik = ticker_to_cik(ticker)
    register_company(ticker, cik)
    return [fetch_filing(f, ticker, force=force)
            for f in list_filings(cik, forms=forms, years=years)]


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("ticker")
    ap.add_argument("--form", default="10-K")
    ap.add_argument("--years", type=int, default=5)
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()

    for r in fetch_company(a.ticker, forms=(a.form,), years=a.years, force=a.force):
        print(f"  doc_id {r['doc_id']:<4} {r['accession']}  period {r['period_end']}  "
              f"{r['bytes']/1e6:6.1f} MB  ixbrl={r['is_ixbrl']}  summary={r['has_summary']}")
