"""Module 5 — EDGAR discovery: ticker → CIK → filing list.

Two SEC endpoints, both cached by src.ingest.edgar.client:
- files/company_tickers.json   ticker → CIK (one file for every US filer)
- data.sec.gov/submissions/    per-filer metadata + filing index

The submissions index keeps only the most recent ~1000 filings inline; older
ones live in paginated side files listed under filings.files. Five years of
10-Ks fit in the recent block for an active filer, so older pages are fetched
only when asked for (include_older=True).

fy / fp are deliberately NOT derived here. DocumentFiscalYearFocus and
DocumentFiscalPeriodFocus are tagged in the filing itself (dei), and the filer's
own answer beats anything inferred from a report date. They are filled in when
facts are parsed.

CLI:  python -m src.ingest.edgar.discover MSFT --form 10-K --years 5
"""
from dataclasses import dataclass
from datetime import date

from src.ingest.edgar.client import EdgarError, fetch_json

TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
ARCHIVE_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{nodash}"


@dataclass(frozen=True)
class Filing:
    """One EDGAR filing, as advertised by the submissions index."""

    accession: str            # '0000950170-24-087843'
    cik: int
    form: str                 # '10-K' | '10-Q' | '8-K' | 'S-1'
    period_end: date | None   # reportDate — the period covered, not the filing date
    filed_date: date
    primary_doc: str          # 'msft-20240630.htm'
    is_ixbrl: bool            # False => facts live in a separate instance .xml
    size: int

    @property
    def nodash(self) -> str:
        return self.accession.replace("-", "")

    @property
    def archive_dir(self) -> str:
        return ARCHIVE_URL.format(cik=self.cik, nodash=self.nodash)

    @property
    def primary_url(self) -> str:
        return f"{self.archive_dir}/{self.primary_doc}"

    @property
    def filing_summary_url(self) -> str:
        return f"{self.archive_dir}/FilingSummary.xml"


def ticker_to_cik(ticker: str, *, force: bool = False) -> int:
    """Resolve a US ticker to its CIK. Raises if unknown — never guesses."""
    wanted = ticker.strip().upper()
    for row in fetch_json(TICKERS_URL, force=force).values():
        if row["ticker"].upper() == wanted:
            return int(row["cik_str"])
    raise EdgarError(f"ticker {ticker!r} is not in SEC's company_tickers.json")


def company_meta(cik: int, *, force: bool = False) -> dict:
    """Filer identity for the companies table."""
    d = fetch_json(SUBMISSIONS_URL.format(cik=cik), force=force)
    fye = d.get("fiscalYearEnd") or ""            # '0630'
    return {
        "cik": int(d["cik"]),
        "name": d["name"],
        "sic": d.get("sic") or None,
        "sic_description": d.get("sicDescription"),
        "tickers": d.get("tickers", []),
        "exchanges": d.get("exchanges", []),
        "fiscal_year_end": f"{fye[:2]}-{fye[2:]}" if len(fye) == 4 else None,
    }


def _rows(block: dict) -> list[dict]:
    """Transpose the submissions index (arrays of columns) into row dicts."""
    keys = ["accessionNumber", "filingDate", "reportDate", "form",
            "primaryDocument", "isInlineXBRL", "size"]
    return [dict(zip(keys, vals)) for vals in zip(*(block[k] for k in keys))]


def _to_filing(row: dict, cik: int) -> Filing:
    return Filing(
        accession=row["accessionNumber"],
        cik=cik,
        form=row["form"],
        period_end=date.fromisoformat(row["reportDate"]) if row["reportDate"] else None,
        filed_date=date.fromisoformat(row["filingDate"]),
        primary_doc=row["primaryDocument"],
        is_ixbrl=bool(row["isInlineXBRL"]),
        size=int(row["size"] or 0),
    )


def list_filings(
    cik: int,
    *,
    forms: tuple[str, ...] = ("10-K",),
    years: int | None = None,
    include_older: bool = False,
    force: bool = False,
) -> list[Filing]:
    """Filings of the given forms, newest first.

    years=5 keeps the 5 most recent matches (not 5 calendar years) — amended and
    re-filed documents make a date window an unreliable way to count filings.
    """
    d = fetch_json(SUBMISSIONS_URL.format(cik=cik), force=force)
    blocks = [d["filings"]["recent"]]
    if include_older:
        for f in d["filings"].get("files", []):
            blocks.append(fetch_json(
                f"https://data.sec.gov/submissions/{f['name']}", force=force))

    out = [_to_filing(r, cik) for b in blocks for r in _rows(b) if r["form"] in forms]
    out.sort(key=lambda f: f.filed_date, reverse=True)
    return out[:years] if years else out


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("ticker")
    ap.add_argument("--form", default="10-K")
    ap.add_argument("--years", type=int, default=5)
    ap.add_argument("--include-older", action="store_true")
    a = ap.parse_args()

    cik = ticker_to_cik(a.ticker)
    meta = company_meta(cik)
    print(f"{a.ticker}  CIK {cik}  {meta['name']}  (FYE {meta['fiscal_year_end']}, "
          f"SIC {meta['sic']} {meta['sic_description']})")
    for f in list_filings(cik, forms=(a.form,), years=a.years, include_older=a.include_older):
        flag = "iXBRL" if f.is_ixbrl else "xml  "
        print(f"  {f.filed_date}  {f.form:6} period {f.period_end}  {flag}  "
              f"{f.size/1e6:6.1f} MB  {f.primary_doc}")
