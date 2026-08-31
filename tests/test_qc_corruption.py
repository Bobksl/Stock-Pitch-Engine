"""P1.5 — the Phase 1 exit criterion.

Audit section 7: "the verifier catches a deliberately corrupted figure in a test
document."

`tests/fixtures/draft_msft_golden.md` is a real Company Overview section built
from MSFT's FY2026 10-K (accession 0001193125-26-323660). It verifies clean.
Every test below breaks it on purpose and asserts the break is caught.

The sweep at the end is stronger than the stated criterion and is the point of
the file: it corrupts EVERY figure in the draft, one at a time, and requires a
100% catch rate. A search-based verifier would score about 4% on the headline
figures (see the measurement in src/qc/anchors.py), so this is the test that
holds the architecture in place -- if someone later "simplifies" resolution back
to searching the facts table, this fails loudly rather than quietly passing.
"""
import re
from decimal import Decimal
from pathlib import Path

import pytest

from src.qc.claims import extract_claims
from src.qc.external import load_records
from src.qc.recency import STALE
from src.qc.report import verify_draft
from src.qc.resolve import (
    MISMATCH,
    MISSING_SOURCE,
    UNANCHORED,
    UNIT_MISMATCH,
    UNKNOWN_ANCHOR,
)

FIXTURES = Path(__file__).parent / "fixtures"
GOLDEN = FIXTURES / "draft_msft_golden.md"
EXTERNALS = FIXTURES / "external_test.yaml"


def has_facts() -> bool:
    try:
        from datetime import date

        from src.facts.api import get_fact
        return get_fact(789019, "revenue", date(2026, 6, 30)) is not None
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not has_facts(), reason="MSFT facts not loaded in this database")


@pytest.fixture(scope="module")
def golden() -> str:
    return GOLDEN.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def externals():
    return load_records(EXTERNALS)


def check(md: str, externals, **kwargs):
    return verify_draft(md, externals=externals, **kwargs)


# --------------------------------------------------------------------------
# baseline -- without this the corruption tests prove nothing
# --------------------------------------------------------------------------

def test_the_golden_draft_verifies_clean(golden, externals):
    report = check(golden, externals)
    assert report.passed, report.render()
    assert len(report.claims) == 26
    assert all(r.ok for r in report.resolutions)
    assert not report.stale


def test_the_golden_draft_exercises_all_three_provenance_classes(golden, externals):
    report = check(golden, externals)
    kinds = {a.kind for a in report.index.values()}
    assert kinds == {"fact", "model", "ext"}


# --------------------------------------------------------------------------
# mutation helpers
# --------------------------------------------------------------------------

_DIGITS = re.compile(r"\d[\d,]*(?:\.\d+)?")


def perturb(md: str, claim, steps: int = 3) -> str:
    """Shift a figure by `steps` units in its last written place.

    Three steps against a half-ulp interval is unambiguously outside it, while
    staying the kind of small, plausible error a review would miss -- 331.8
    becomes 332.1, not 900.
    """
    m = _DIGITS.search(claim.text)
    exponent = claim.digits.as_tuple().exponent
    shifted = abs(claim.digits) + steps * Decimal(1).scaleb(exponent)
    decimals = max(0, -exponent)
    rendered = (f"{shifted:,.{decimals}f}" if "," in m.group(0)
                else f"{shifted:.{decimals}f}")
    replaced = claim.text[:m.start()] + rendered + claim.text[m.end():]
    return md[:claim.span[0]] + replaced + md[claim.span[1]:]


def failure_at(report, offset: int):
    return next((r for r in report.failures if r.claim.span[0] == offset), None)


def claim_named(md: str, needle: str):
    return next(c for c in extract_claims(md) if c.text == needle)


# --------------------------------------------------------------------------
# the stated exit criterion, one class at a time
# --------------------------------------------------------------------------

def test_a_corrupted_headline_figure_is_caught(golden, externals):
    """$331.8 billion -> $332.1 billion. The figure a pitch leads with."""
    broken = golden.replace("$331.8 billion [^F1]", "$332.1 billion [^F1]")
    report = check(broken, externals)
    assert not report.passed
    failures = report.failures
    assert len(failures) == 1
    assert failures[0].status == MISMATCH
    assert failures[0].actual == Decimal("331839000000")
    assert "331,839,000,000" in failures[0].detail


def test_the_failure_localises_to_a_position_in_the_draft(golden, externals):
    broken = golden.replace("$331.8 billion [^F1]", "$332.1 billion [^F1]")
    failure = check(broken, externals).failures[0]
    assert failure.claim.text == "$332.1 billion"
    assert broken[slice(*failure.claim.span)] == "$332.1 billion"
    assert failure.claim.line == 11


def test_a_corrupted_table_cell_is_caught(golden, externals):
    broken = golden.replace("| 137,791 [^F11]", "| 137,891 [^F11]")
    report = check(broken, externals)
    assert not report.passed
    assert [f.status for f in report.failures] == [MISMATCH]


def test_a_scale_corruption_is_caught(golden, externals):
    """billion -> million, the error a value comparison alone would miss."""
    broken = golden.replace("$155.2 billion [^F3]", "$155.2 million [^F3]")
    report = check(broken, externals)
    assert not report.passed
    failure = report.failures[0]
    assert failure.status == MISMATCH
    assert "scale 1,000,000,000" in failure.detail


def test_a_sign_flip_is_caught(golden, externals):
    broken = golden.replace("| 14,386 [^F14]", "| (14,386) [^F14]")
    report = check(broken, externals)
    assert not report.passed
    assert report.failures[0].claim.value == Decimal("-14386000000")


def test_a_corrupted_derived_figure_is_caught(golden, externals):
    """The model cell is recomputed, so a wrong margin cannot hide behind a
    correctly-declared cell."""
    broken = golden.replace("46.8% [^M1]", "48.2% [^M1]")
    report = check(broken, externals)
    assert not report.passed
    assert report.failures[0].status == MISMATCH


def test_a_corrupted_external_figure_is_caught(golden, externals):
    broken = golden.replace("$512.40 [^E1]", "$612.40 [^E1]")
    report = check(broken, externals)
    assert not report.passed
    assert [f.status for f in report.failures] == [MISMATCH]
    # Exactly one failure, and that is correct: the P/E cell recomputes from the
    # RECORD, not from the prose, so the multiple stays right while the quoted
    # price is caught. Recomputation is what keeps the two independent.
    assert report.failures[0].actual == Decimal("512.40")


# --------------------------------------------------------------------------
# corrupting the CITATION rather than the figure
# --------------------------------------------------------------------------

def test_an_anchor_swapped_to_another_segment_is_caught(golden, externals):
    """Right number, wrong citation: Intelligent Cloud revenue attributed to
    the Productivity segment."""
    broken = golden.replace("| 137,791 [^F11]", "| 137,791 [^F9]")
    report = check(broken, externals)
    assert not report.passed
    assert report.failures[0].actual == Decimal("139996000000")


def test_an_anchor_swapped_to_a_prior_period_is_caught(golden, externals):
    broken = golden.replace(
        "F1:  {kind: fact, cik: 789019, concept: revenue, period_end: 2026-06-30}",
        "F1:  {kind: fact, cik: 789019, concept: revenue, period_end: 2025-06-30}")
    report = check(broken, externals)
    assert not report.passed
    assert report.failures[0].actual == Decimal("281724000000")


def test_a_stripped_anchor_is_caught(golden, externals):
    broken = golden.replace("$12.4 billion [^F6]", "$12.4 billion")
    report = check(broken, externals)
    assert not report.passed
    assert report.failures[0].status == UNANCHORED


def test_stripping_an_anchor_mid_line_binds_to_the_next_one_and_still_fails(
        golden, externals):
    """Anchors bind backwards, so deleting one makes the figure claim the NEXT
    anchor on its line rather than silently passing. Here a dollar figure ends
    up citing a margin cell, which fails on units -- a different message from
    UNANCHORED, but the figure does not escape."""
    broken = golden.replace("$35.6 billion [^F5], or 10.7% [^M8]",
                            "$35.6 billion, or 10.7% [^M8]")
    report = check(broken, externals)
    assert not report.passed
    assert report.failures[0].status == UNIT_MISMATCH


def test_an_anchor_with_no_index_entry_is_caught(golden, externals):
    broken = golden.replace("$35.6 billion [^F5]", "$35.6 billion [^F99]")
    report = check(broken, externals)
    assert not report.passed
    assert report.failures[0].status == UNKNOWN_ANCHOR


def test_a_deleted_index_entry_is_caught(golden, externals):
    broken = re.sub(r"^F5: .*$", "", golden, flags=re.MULTILINE)
    report = check(broken, externals)
    assert not report.passed
    assert report.failures[0].status == UNKNOWN_ANCHOR


def test_a_missing_external_store_is_caught(golden):
    report = verify_draft(golden, externals={})
    assert not report.passed
    assert MISSING_SOURCE in {f.status for f in report.failures}


def test_a_deleted_model_cell_is_caught(golden, externals):
    broken = re.sub(r"^rnd_intensity_fy26:.*?(?=^\w)", "", golden,
                    flags=re.MULTILINE | re.DOTALL)
    report = check(broken, externals)
    assert not report.passed
    assert report.failures[0].status == MISSING_SOURCE


def test_a_model_cell_pointed_at_the_wrong_input_is_caught(golden, externals):
    """The cell still computes and still cites facts -- but the wrong ones."""
    broken = golden.replace(
        """rnd_intensity_fy26:
  op: ratio
  quantize: "0.000001"
  inputs:
    - {cik: 789019, concept: research_and_development, period_end: 2026-06-30}""",
        """rnd_intensity_fy26:
  op: ratio
  quantize: "0.000001"
  inputs:
    - {cik: 789019, concept: share_based_compensation, period_end: 2026-06-30}""")
    assert broken != golden
    report = check(broken, externals)
    assert not report.passed
    assert report.failures[0].status == MISMATCH


# --------------------------------------------------------------------------
# staleness (C12 / framework 6.3)
# --------------------------------------------------------------------------

def test_a_prior_year_figure_without_its_comparative_is_stale(golden, externals):
    """Delete the current-year sentence and the prior-year figures beside it
    become stale -- framework 6.3's rule is about the SET of figures."""
    broken = golden.replace(
        "and its revenue fell from $54.6 billion [^F15] a year\nearlier",
        "and its revenue was $54.6 billion [^F15] in the prior year")
    broken = broken.replace("| 54,052 [^F13] | 14,386 [^F14] |",
                            "| 14,386 [^F14] | 14,386 [^F14] |")
    report = check(broken, externals)
    assert not report.passed
    assert any(f.status == STALE for f in report.recency)
    stale = next(f for f in report.recency if f.status == STALE)
    assert stale.latest_available.isoformat() == "2026-06-30"
    assert "latest filed period is 2026-06-30" in stale.detail


def test_as_of_makes_a_current_draft_stale_against_an_earlier_date(golden, externals):
    """The same draft read as of a date before the FY2026 10-K was filed: the
    figures it quotes were not knowable then (Audit G6)."""
    from datetime import date
    report = check(golden, externals, as_of=date(2025, 12, 31))
    assert not report.passed
    assert MISSING_SOURCE in {f.status for f in report.failures}


# --------------------------------------------------------------------------
# the sweep -- every figure, one at a time, 100% required
# --------------------------------------------------------------------------

def test_every_figure_in_the_draft_is_individually_catchable(golden, externals):
    baseline = check(golden, externals)
    assert baseline.passed

    escaped: list[str] = []
    for claim in baseline.claims:
        broken = perturb(golden, claim)
        assert broken != golden, f"perturbation was a no-op for {claim.text!r}"
        report = check(broken, externals)
        if report.passed or failure_at(report, claim.span[0]) is None:
            escaped.append(f"line {claim.line}: {claim.text!r}")

    assert not escaped, (
        f"{len(escaped)} of {len(baseline.claims)} corrupted figures went "
        f"undetected:\n  " + "\n  ".join(escaped))


def test_the_sweep_covers_every_provenance_class(golden, externals):
    """Guards the sweep itself: a draft that lost its model or external
    citations would still sweep clean while testing much less."""
    report = check(golden, externals)
    anchored = [report.index[c.anchor].kind for c in report.claims if c.anchor]
    assert len(anchored) == len(report.claims)
    assert anchored.count("fact") >= 10
    assert anchored.count("model") >= 5
    assert anchored.count("ext") >= 1
