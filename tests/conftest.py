"""Shared fixtures. Run the suite as `python -m pytest` from the repo root."""
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="session")
def tsmc_workbook() -> Path:
    """The Phase 2 acceptance fixture on disk (Audit section 2)."""
    return FIXTURES / "tsmc_model.xlsx"


@pytest.fixture(scope="session")
def tsmc_model(tsmc_workbook):
    """That workbook, read: its declared inputs and the conventions it implements."""
    from src.valuation.excel.reader import read_model
    return read_model(tsmc_workbook, published_price_cell="B27")
