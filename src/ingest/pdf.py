"""Module 1 — Ingestion / OCR.

Extract text per page with pdfplumber; if a page yields < OCR_MIN_CHARS chars,
rasterize it (pdf2image + poppler) and OCR with pytesseract (chi_tra+eng).
Writes companies / documents / pages rows.

Filename convention carries metadata: 0700_HK_2025_annual.pdf

CLI:  python -m src.ingest.pdf sample_pdfs/0700_HK_2025_annual.pdf [--no-ocr]
"""
import re
import sys
from pathlib import Path

import pdfplumber

from src.config import OCR_LANG, OCR_MIN_CHARS, POPPLER_PATH, TESSDATA_DIR, TESSERACT_CMD
from src.db import get_conn

# Broken-font marker: pdfplumber emits "(cid:NN)" when a PDF font has no usable
# Unicode mapping (e.g. HSBC AR 2025). Such text is unsearchable garbage -> OCR the page.
CID_RE = re.compile(r"\(cid:\d+\)")

FILENAME_RE = re.compile(r"(?P<code>\d{4,5})_HK_(?P<year>\d{4})_(?P<dtype>annual|interim)", re.I)

# Small known-issuer map; unknown tickers fall back to the ticker itself (fix later via cover-page regex).
COMPANY_NAMES = {
    "0700.HK": "Tencent Holdings Limited",
    "0005.HK": "HSBC Holdings plc",
    "9626.HK": "Bilibili Inc.",
}


def parse_filename(pdf_path: str) -> dict:
    m = FILENAME_RE.search(Path(pdf_path).stem)
    if not m:
        raise ValueError(f"Filename must look like 0700_HK_2025_annual.pdf, got: {pdf_path}")
    ticker = f"{m['code'].zfill(4)}.HK"
    return {"ticker": ticker, "fiscal_year": int(m["year"]), "doc_type": m["dtype"].lower()}


def ocr_page(pdf_path: str, page_num: int) -> str:
    """Rasterize one page and OCR it (Traditional Chinese + English)."""
    import os

    import pytesseract
    from pdf2image import convert_from_path

    pytesseract.pytesseract.tesseract_cmd = TESSERACT_CMD
    # env var instead of --tessdata-dir: pytesseract passes config quotes literally, breaking the path
    os.environ["TESSDATA_PREFIX"] = TESSDATA_DIR
    img = convert_from_path(
        pdf_path, dpi=200, first_page=page_num, last_page=page_num, poppler_path=POPPLER_PATH
    )[0]
    return pytesseract.image_to_string(img, lang=OCR_LANG)


def extract_pages(pdf_path: str, use_ocr: bool = True) -> list[dict]:
    """Return [{'page_num', 'text', 'extraction'}, ...] for every page."""
    pages = []
    with pdfplumber.open(pdf_path) as pdf:
        total = len(pdf.pages)
        for i, page in enumerate(pdf.pages, start=1):
            raw = (page.extract_text() or "").strip()
            text = CID_RE.sub("", raw).strip()  # never store cid garbage
            extraction = "pdfplumber"
            # OCR when too little text survives OR >30% of the page was cid garbage
            if use_ocr and (len(text) < OCR_MIN_CHARS or len(text) < 0.7 * len(raw)):
                try:
                    text = ocr_page(pdf_path, i).strip()
                    extraction = "ocr"
                except Exception as e:  # OCR must never sink ingestion
                    print(f"  page {i}: OCR failed ({type(e).__name__}: {e}); keeping extracted text")
            pages.append({"page_num": i, "text": text, "extraction": extraction})
            if i % 50 == 0 or i == total:
                print(f"  extracted {i}/{total} pages")
    return pages


def ingest(pdf_path: str, use_ocr: bool = True) -> int:
    """Idempotent per source_path: re-ingesting the same file replaces its rows. Returns doc_id."""
    meta = parse_filename(pdf_path)
    source = str(Path(pdf_path).resolve())
    print(f"Ingesting {source} -> {meta}")
    pages = extract_pages(pdf_path, use_ocr=use_ocr)
    n_ocr = sum(1 for p in pages if p["extraction"] == "ocr")

    with get_conn() as conn:
        conn.execute(
            "INSERT INTO companies (ticker, company_name) VALUES (%s, %s) ON CONFLICT (ticker) DO NOTHING",
            (meta["ticker"], COMPANY_NAMES.get(meta["ticker"], meta["ticker"])),
        )
        conn.execute("DELETE FROM documents WHERE source_path = %s", (source,))  # cascades pages/chunks
        doc_id = conn.execute(
            """INSERT INTO documents (ticker, fiscal_year, doc_type, source_path, page_count, is_scanned)
               VALUES (%s, %s, %s, %s, %s, %s) RETURNING doc_id""",
            (meta["ticker"], meta["fiscal_year"], meta["doc_type"], source, len(pages), n_ocr > len(pages) / 2),
        ).fetchone()[0]
        with conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO pages (doc_id, page_num, raw_text, extraction) VALUES (%s, %s, %s, %s)",
                [(doc_id, p["page_num"], p["text"], p["extraction"]) for p in pages],
            )
    print(f"doc_id={doc_id}: {len(pages)} pages stored ({n_ocr} via OCR)")
    return doc_id


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    ingest(args[0], use_ocr="--no-ocr" not in sys.argv)
