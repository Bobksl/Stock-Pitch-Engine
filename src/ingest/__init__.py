"""Ingestion: filings in, text and facts out.

Two routes. `edgar/` is the primary path for US filers -- HTML and inline
XBRL, no OCR needed. `pdf.py` is the secondary route for filings EDGAR does
not carry, where OCR is unavoidable.
"""
