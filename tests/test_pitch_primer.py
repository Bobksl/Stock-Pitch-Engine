"""P3.8 — framework 2.8: the industry primer, versioned and content-addressed.

    "Industry work is cached as a versioned primer, reusable across names in
     the same sector, refreshed quarterly. Pitches reference a primer version.
     Saves duplicated effort and enforces internal consistency across your
     coverage."

The version is a digest of the CONTENT, not a counter. Two sessions deriving
the same industry work get the same version, an edited primer gets a different
one, and a pitch that says it used `semiconductors@2025Q4#a1b2c3d4e5f6` names
something that can be checked rather than something that can be re-labelled.

The cache boundary is the load-bearing decision. Structure is shared; relative
position is not. 2.5h's "company growth minus peer-median growth" is a
statement about ONE company, and caching it into a sector primer would carry
one name's conclusion silently onto the next.
"""
from datetime import date

import pytest

from src.pitch.primer import (
    Primer,
    PrimerError,
    load_primer,
    quarter_of,
    save_primer,
)

CONTENT = dict(
    industry_key="semiconductors",
    comp_set=[
        {"ticker": "MRVL", "tiers": ["direct_competitor"],
         "covers_type": "Semiconductor Solutions",
         "justification": "Custom silicon sold to the same hyperscaler buyers."},
        {"ticker": "IBM", "tiers": ["valuation_reference"],
         "covers_type": "Infrastructure Software",
         "justification": "Acquire-and-harvest maintenance economics."},
    ],
    structural_conclusion="Rivalry runs on design wins and roadmap timing.",
    profit_capture_conclusion="Profit sits with the design owners.",
    alignment={"aligned": {"MRVL": 333}, "excluded": {"MSFT": "184 days"}},
)


def primer(quarter="2025Q4", **over):
    return Primer(quarter=quarter, created_on=date(2025, 12, 1),
                  **{**CONTENT, **over})


class TestQuarters:
    def test_a_date_maps_to_its_calendar_quarter(self):
        assert quarter_of(date(2025, 11, 2)) == "2025Q4"
        assert quarter_of(date(2025, 1, 1)) == "2025Q1"
        assert quarter_of(date(2025, 6, 30)) == "2025Q2"
        assert quarter_of(date(2025, 9, 30)) == "2025Q3"


class TestTheVersionIsContentAddressed:
    def test_the_same_content_always_gets_the_same_version(self):
        assert primer().version == primer().version

    def test_the_creation_date_does_not_change_the_version(self):
        """Re-deriving the same industry work is the same primer. A timestamp
        in the digest would make every re-run a new version and defeat the
        point of addressing by content."""
        later = Primer(quarter="2025Q4", created_on=date(2026, 3, 1), **CONTENT)
        assert later.version == primer().version

    def test_editing_a_conclusion_changes_the_version(self):
        edited = primer(structural_conclusion="Actually it is a price war.")
        assert edited.version != primer().version

    def test_editing_a_justification_changes_the_version(self):
        members = [dict(m) for m in CONTENT["comp_set"]]
        members[0]["justification"] = "Different reason entirely."
        assert primer(comp_set=members).version != primer().version

    def test_a_different_quarter_is_a_different_version(self):
        assert primer(quarter="2026Q1").version != primer().version

    def test_the_version_reads_as_industry_quarter_and_digest(self):
        v = primer().version
        key, rest = v.split("@")
        quarter, digest = rest.split("#")
        assert key == "semiconductors" and quarter == "2025Q4"
        assert len(digest) == 12 and digest.isalnum()


class TestExpiry:
    def test_a_primer_is_live_in_its_own_quarter(self):
        assert primer().live(date(2025, 12, 31)) is True

    def test_a_primer_is_live_through_the_following_quarter(self):
        """2.8 says refreshed quarterly. Dying the instant its own quarter ends
        would leave no window in which to refresh it; one quarter of runway and
        no more is the reading."""
        assert primer().live(date(2026, 3, 31)) is True

    def test_a_primer_two_quarters_old_is_expired(self):
        assert primer().live(date(2026, 4, 1)) is False

    def test_the_expiry_quarter_is_stated(self):
        assert primer().expires_after == "2026Q1"

    def test_reusing_an_expired_primer_blocks(self):
        """No warning tier: 6.5 has one passing state, and a stale primer is
        either usable or it is not."""
        with pytest.raises(PrimerError, match="expired"):
            primer().require_live(date(2026, 6, 1))

    def test_requiring_a_live_primer_returns_it(self):
        p = primer()
        assert p.require_live(date(2026, 1, 15)) is p


class TestTheCacheBoundary:
    def test_a_primer_carries_structure_and_the_comp_set(self):
        p = primer()
        assert p.structural_conclusion and p.profit_capture_conclusion
        assert len(p.comp_set) == 2

    def test_a_primer_refuses_company_specific_relative_position(self):
        """2.5h's company growth minus peer-median growth is a statement about
        ONE company. Caching it into a sector primer would carry one name's
        conclusion silently onto the next pitch in the same sector, which is
        the opposite of the consistency 2.8 is for."""
        with pytest.raises(PrimerError, match="relative position"):
            primer(relative_position={"AVGO": "+8pp vs peer median"})

    def test_a_primer_refuses_an_empty_comp_set(self):
        with pytest.raises(PrimerError, match="comp set"):
            primer(comp_set=[])

    def test_a_primer_refuses_a_missing_structural_conclusion(self):
        with pytest.raises(PrimerError, match="structural"):
            primer(structural_conclusion="")


class TestRoundTrip:
    def test_a_saved_primer_loads_back_identical(self, tmp_path):
        p = primer()
        path = save_primer(p, root=tmp_path)
        assert load_primer(path).version == p.version

    def test_the_path_is_the_industry_and_the_quarter(self, tmp_path):
        path = save_primer(primer(), root=tmp_path)
        assert path.parent.name == "semiconductors"
        assert path.stem == "2025Q4"

    def test_a_tampered_file_fails_to_load(self, tmp_path):
        """The stored version is checked against the content it claims to
        describe. Editing the file without re-deriving the digest is exactly
        the silent re-label content addressing exists to prevent."""
        path = save_primer(primer(), root=tmp_path)
        text = path.read_text(encoding="utf-8")
        path.write_text(text.replace("design wins", "price"), encoding="utf-8")
        with pytest.raises(PrimerError, match="does not match"):
            load_primer(path)
