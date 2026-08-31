"""P0.3 — discovery: ticker → CIK, submissions index → Filing objects, URLs.

Network-free: discover.fetch_json is patched. Fixture values are real MSFT
values taken from live responses, so the shapes match what SEC actually serves.
"""
from datetime import date

import pytest

from src.edgar import discover
from src.edgar.client import EdgarError

TICKERS = {
    "0": {"cik_str": 789019, "ticker": "MSFT", "title": "MICROSOFT CORP"},
    "1": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."},
}

# Column-major, exactly like filings.recent in the submissions index.
RECENT = {
    "accessionNumber": ["0000950170-24-087843", "0000950170-24-000001", "0001193125-23-000001"],
    "filingDate":      ["2024-07-30", "2024-04-25", "2023-07-27"],
    "reportDate":      ["2024-06-30", "2024-03-31", "2023-06-30"],
    "form":            ["10-K", "10-Q", "10-K"],
    "primaryDocument": ["msft-20240630.htm", "msft-20240331.htm", "msft-20230630.htm"],
    "isInlineXBRL":    [1, 1, 1],
    "size":            [30400000, 8000000, 41000000],
}
OLDER = {
    "accessionNumber": ["0001193125-18-000001"],
    "filingDate":      ["2018-08-03"],
    "reportDate":      ["2018-06-30"],
    "form":            ["10-K"],
    "primaryDocument": ["msft-10k_20180630.htm"],
    "isInlineXBRL":    [0],
    "size":            [12000000],
}
SUBMISSIONS = {
    "cik": 789019,
    "name": "MICROSOFT CORP",
    "sic": "7372",
    "sicDescription": "Services-Prepackaged Software",
    "tickers": ["MSFT"],
    "exchanges": ["Nasdaq"],
    "fiscalYearEnd": "0630",
    "filings": {
        "recent": RECENT,
        "files": [{"name": "CIK0000789019-submissions-001.json"}],
    },
}


@pytest.fixture
def offline(monkeypatch):
    def fake(url, *, force=False):
        if url == discover.TICKERS_URL:
            return TICKERS
        if url.endswith("submissions-001.json"):
            return OLDER
        if "submissions/CIK" in url:
            return SUBMISSIONS
        raise AssertionError(f"unexpected URL: {url}")

    monkeypatch.setattr(discover, "fetch_json", fake)


def test_ticker_to_cik(offline):
    assert discover.ticker_to_cik("MSFT") == 789019
    assert discover.ticker_to_cik("aapl") == 320193, "lookup is case-insensitive"


def test_unknown_ticker_raises_rather_than_guessing(offline):
    with pytest.raises(EdgarError, match="NOTATICKER"):
        discover.ticker_to_cik("NOTATICKER")


def test_company_meta_normalises_fiscal_year_end(offline):
    m = discover.company_meta(789019)
    assert m["name"] == "MICROSOFT CORP"
    assert m["fiscal_year_end"] == "06-30", "'0630' becomes 'MM-DD'"
    assert m["sic"] == "7372"


def test_filing_parsed_from_the_index(offline):
    f = discover.list_filings(789019, forms=("10-K",), years=1)[0]
    assert f.accession == "0000950170-24-087843"
    assert f.filed_date == date(2024, 7, 30)
    assert f.period_end == date(2024, 6, 30)
    assert f.is_ixbrl is True
    assert f.size == 30400000


def test_filing_urls_are_built_from_the_accession():
    f = discover.Filing("0000950170-24-087843", 789019, "10-K",
                        date(2024, 6, 30), date(2024, 7, 30),
                        "msft-20240630.htm", True, 30400000)
    base = "https://www.sec.gov/Archives/edgar/data/789019/000095017024087843"
    assert f.nodash == "000095017024087843"
    assert f.archive_dir == base
    assert f.primary_url == f"{base}/msft-20240630.htm"
    assert f.filing_summary_url == f"{base}/FilingSummary.xml"


def test_list_filings_filters_by_form(offline):
    forms = {f.form for f in discover.list_filings(789019, forms=("10-K",))}
    assert forms == {"10-K"}


def test_list_filings_is_newest_first_and_limited(offline):
    got = discover.list_filings(789019, forms=("10-K", "10-Q"), years=2)
    assert [f.filed_date for f in got] == [date(2024, 7, 30), date(2024, 4, 25)]


def test_older_pages_are_fetched_only_when_asked(offline):
    recent_only = discover.list_filings(789019, forms=("10-K",))
    with_older = discover.list_filings(789019, forms=("10-K",), include_older=True)
    assert len(recent_only) == 2
    assert len(with_older) == 3
    assert with_older[-1].is_ixbrl is False, "pre-2019 filings carry a separate instance"
