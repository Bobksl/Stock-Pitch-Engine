"""P3.2 — framework 7, the sector KPI taxonomy.

Section 7 asks for a fixed list per sub-group, each entry carrying a name, a
definition, a source (an XBRL tag or filing text), and whether it is disclosed
or derived. The taxonomy is data in `config/kpi_taxonomy.yaml` for the reason
`concept_map.yaml` is data: how a number is produced must be visible in a diff.

The load-bearing property is that a derived KPI is a **model cell**. It carries
an op from the closed vocabulary in `cells.py` and its inputs are concept names,
so the KPI snapshot is recomputed at verification time and never stored. No new
provenance machinery, and 6.4 already covers it.

Hand-checked values below come from AVGO FY2025 as filed. The arithmetic is
stated in each test so a reader can redo it without running anything.
"""
from datetime import date
from decimal import Decimal

import pytest

from src.pitch.kpi import (
    DERIVED,
    DISCLOSED,
    FILING_TEXT,
    KpiError,
    declarations_for,
    load_taxonomy,
    sub_group,
)

AVGO = 1730168
FY2025, FY2024 = date(2025, 11, 2), date(2024, 11, 3)
Q = Decimal("0.0001")


# ---------------------------------------------------------------------------
# The taxonomy is data, and it is validated when it loads
# ---------------------------------------------------------------------------

class TestTheTaxonomy:
    def test_every_section_7_sub_group_is_present(self):
        assert sorted(load_taxonomy()) == [
            "hardware", "it_services", "semiconductors", "software_saas"]

    def test_each_sub_group_cites_its_spec_section(self):
        assert sub_group("software_saas").spec_ref == "7.1"
        assert sub_group("semiconductors").spec_ref == "7.2"
        assert sub_group("hardware").spec_ref == "7.3"
        assert sub_group("it_services").spec_ref == "7.4"

    def test_every_kpi_carries_the_four_fields_section_7_requires(self):
        for group in load_taxonomy().values():
            for kpi in group.kpis:
                assert kpi.name and kpi.definition
                assert kpi.disclosure in (DISCLOSED, DERIVED)
                assert kpi.source is not None or kpi.derivation is not None

    def test_the_semis_group_carries_the_cycle_kpis(self):
        """7.2 names ASP and unit volume separately, and book-to-bill."""
        names = {k.name for k in sub_group("semiconductors").kpis}
        assert {"asp", "unit_volume", "book_to_bill", "inventory_days",
                "capex_intensity", "rd_intensity"} <= names


class TestDisclosedVersusDerived:
    """The split that decided spec v1.3's 6.4 amendment."""

    def test_roughly_half_the_taxonomy_is_disclosed_in_prose(self):
        kpis = [k for g in load_taxonomy().values() for k in g.kpis]
        text = [k for k in kpis if k.source == FILING_TEXT]
        assert len(text) >= len(kpis) // 3, (
            "if this ever drops low, revisit whether filing_text_disclosure "
            "still earns its place in the 6.4 vocabulary")

    def test_a_prose_kpi_declares_filing_text_as_its_source(self):
        assert sub_group("semiconductors").kpi("book_to_bill").source == FILING_TEXT

    def test_an_xbrl_disclosed_kpi_names_a_concept_not_a_tag(self):
        """The concept map owns tag resolution; the taxonomy must not fork it."""
        kpi = sub_group("semiconductors").kpi("inventory")
        assert kpi.disclosure == DISCLOSED
        assert kpi.source == {"concept": "inventory"}

    def test_a_derived_kpi_declares_an_op_from_the_closed_vocabulary(self):
        from src.qc.cells import OPS
        for group in load_taxonomy().values():
            for kpi in group.kpis:
                if kpi.disclosure == DERIVED:
                    assert kpi.derivation["op"] in OPS


# ---------------------------------------------------------------------------
# Instantiation: taxonomy template -> model cell declarations
# ---------------------------------------------------------------------------

class TestDeclarations:
    def setup_method(self):
        self.decls = declarations_for("semiconductors", AVGO, [FY2025, FY2024])

    def test_only_derived_kpis_become_cells(self):
        """A disclosed KPI is a fact or an external record, not a computation."""
        assert "inventory_days" in self.decls
        assert "inventory" not in self.decls
        assert "book_to_bill" not in self.decls

    def test_a_concept_input_becomes_a_fact_reference(self):
        rd = self.decls["rd_intensity"]
        assert rd["op"] == "ratio"
        assert rd["inputs"][0] == {
            "cik": AVGO, "concept": "research_and_development",
            "period_end": FY2025, "segments": {}}

    def test_a_kpi_input_becomes_a_cell_reference(self):
        assert {"cell": "inventory_turns"} in self.decls["inventory_days"]["inputs"]

    def test_periods_ago_resolves_against_the_period_list(self):
        prior = declarations_for("software_saas", AVGO, [FY2025, FY2024])
        inputs = prior["revenue_growth"]["inputs"]
        assert [i["period_end"] for i in inputs] == [FY2025, FY2024]

    def test_a_literal_input_keeps_its_note(self):
        """cells.py refuses an undocumented constant; the taxonomy supplies one."""
        days = [i for i in self.decls["inventory_days"]["inputs"] if "literal" in i]
        assert len(days) == 1 and days[0]["note"]


class TestRefusals:
    def test_an_unknown_sub_group_names_what_was_asked_for(self):
        with pytest.raises(KpiError, match="biotech"):
            sub_group("biotech")

    def test_a_derived_kpi_naming_an_unmapped_concept_refuses_at_load(self):
        bad = """
        version: 1
        sub_groups:
          x:
            label: X
            spec_ref: "7.9"
            kpis:
              y:
                definition: d
                disclosure: derived
                derivation:
                  op: ratio
                  inputs: [{concept: ebitda}, {concept: revenue}]
        """
        with pytest.raises(KpiError, match="ebitda"):
            load_taxonomy(text=bad)

    def test_a_derived_kpi_naming_an_unknown_op_refuses_at_load(self):
        bad = """
        version: 1
        sub_groups:
          x:
            label: X
            spec_ref: "7.9"
            kpis:
              y:
                definition: d
                disclosure: derived
                derivation:
                  op: compound
                  inputs: [{concept: revenue}, {concept: revenue}]
        """
        with pytest.raises(KpiError, match="compound"):
            load_taxonomy(text=bad)

    def test_a_prose_kpi_used_as_a_derived_input_needs_its_external_record(self):
        """7.4 revenue per employee: headcount is disclosed in prose and has no
        facts row, so the figure cannot be computed until a record supplies it."""
        with pytest.raises(KpiError, match="headcount"):
            declarations_for("it_services", AVGO, [FY2025])

    def test_supplying_the_record_key_resolves_it(self):
        decls = declarations_for("it_services", AVGO, [FY2025],
                                 external_keys={"headcount": "avgo_headcount_fy25"})
        assert {"external": "avgo_headcount_fy25"} in \
            decls["revenue_per_employee"]["inputs"]

    def test_an_empty_period_list_refuses(self):
        with pytest.raises(KpiError, match="no periods"):
            declarations_for("semiconductors", AVGO, [])


# ---------------------------------------------------------------------------
# DB-backed: the cells actually recompute, from AVGO as filed
# ---------------------------------------------------------------------------

def _loaded(cik) -> bool:
    try:
        from src.db import get_conn
        with get_conn() as conn:
            return conn.execute(
                "SELECT count(*) > 0 FROM facts WHERE cik = %s", (cik,)).fetchone()[0]
    except Exception:
        return False


loaded = pytest.mark.skipif(not _loaded(AVGO), reason="AVGO facts not loaded")


@loaded
def test_rd_intensity_recomputes_from_the_filing():
    """AVGO FY2025 R&D 10,977 / revenue 63,887 = 17.18%."""
    from src.qc.cells import CellRegistry
    reg = CellRegistry(declarations=declarations_for(
        "semiconductors", AVGO, [FY2025, FY2024]))
    assert reg.compute("rd_intensity").value.quantize(Q) == Decimal("0.1718")


@loaded
def test_inventory_days_composes_a_cell_a_fact_and_a_literal():
    """2,270 / 20,593 = 0.110232 turns; x 365 = 40.23 days.

    The instant matters more than the arithmetic here: inventory at the fiscal
    year end is 2,270, and the latest inventory instant in the table is a later
    quarter-end carried in by companyfacts. A KPI snapshot pinned to a period
    has to say which instant it means.
    """
    from src.qc.cells import CellRegistry
    reg = CellRegistry(declarations=declarations_for(
        "semiconductors", AVGO, [FY2025, FY2024]))
    assert reg.compute("inventory_turns").value.quantize(Q) == Decimal("0.1102")
    assert reg.compute("inventory_days").value == Decimal("40.23")


@loaded
def test_revenue_growth_recomputes_across_two_periods():
    """63,887 / 51,574 - 1 = 23.87%."""
    from src.qc.cells import CellRegistry
    reg = CellRegistry(declarations=declarations_for(
        "software_saas", AVGO, [FY2025, FY2024]))
    assert reg.compute("revenue_growth").value.quantize(Q) == Decimal("0.2387")


@loaded
def test_a_derived_kpi_cites_every_fact_underneath_it():
    """6.4: a model cell cites its formula and each fact it stands on."""
    from src.qc.cells import CellRegistry
    reg = CellRegistry(declarations=declarations_for(
        "semiconductors", AVGO, [FY2025, FY2024]))
    citation = reg.compute("rd_intensity").citation
    assert "model:rd_intensity = ratio(" in citation
    assert citation.count("<-") == 2
