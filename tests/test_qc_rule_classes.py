"""P2.4 — Class A / Class B, exception records, and the one passing state.

The tests that matter here are the refusals. Anyone can write a gate that
accepts a well-formed exception; the design claim of framework 6.5 is that a
Class A rule *cannot* be excepted, and the way that claim is earned is that
such a record fails to parse rather than failing to apply. So the important
assertions below are the ones where nothing gets built.
"""
from datetime import date
from decimal import Decimal

import pytest

from src.qc.exceptions import (
    EXCEPTION_REASONS,
    ExceptionError,
    ExceptionRecord,
    for_rule,
    load_exceptions,
)
from src.qc.findings import Finding, FindingSet, Measurement, apply_exceptions
from src.qc.rules import (
    AUDIT_FINDINGS,
    CLASS_A,
    CLASS_B,
    DEFECTS,
    RULES,
    UnknownRule,
    by_class,
    rule,
)

TODAY = date(2026, 9, 1)

LONG_DURATION = """
tv_share_infra:
  condition: terminal_value_share
  measured: 0.868
  reason: long_duration_asset
  detail: TV share 86.8%, above the 75% threshold
  author: Bob Liang
  date: 2026-08-31
  expiry: 2027-02-28
"""


class TestTheRegistry:
    def test_every_rule_is_class_a_or_class_b(self):
        """6.5: every QC rule is Class A or Class B. There is no third."""
        assert {r.rule_class for r in RULES.values()} == {CLASS_A, CLASS_B}

    def test_only_class_b_is_exceptionable(self):
        assert all(not r.exceptionable for r in by_class(CLASS_A))
        assert all(r.exceptionable for r in by_class(CLASS_B))

    def test_all_eight_exit_criterion_defects_have_a_rule(self):
        assert sorted(DEFECTS) == [1, 2, 3, 4, 5, 6, 7, 8]

    def test_the_defect_classes_match_the_exit_criterion_table(self):
        expected = {1: CLASS_A, 2: CLASS_B, 3: CLASS_B, 4: CLASS_A,
                    5: CLASS_A, 6: CLASS_A, 7: CLASS_A, 8: CLASS_B}
        assert {n: rule(rid).rule_class for n, rid in DEFECTS.items()} == expected

    def test_the_audit_numbering_maps_onto_the_exit_criterion_numbering(self):
        """The audit folds TV share and the spread into one 'Finding 2'."""
        assert AUDIT_FINDINGS[2] == (2, 3)
        assert sorted({d for ds in AUDIT_FINDINGS.values() for d in ds}) == [
            1, 2, 3, 4, 5, 6, 7, 8]

    def test_an_unknown_rule_id_names_what_was_asked_for(self):
        with pytest.raises(UnknownRule, match="tv_share_warning"):
            rule("tv_share_warning")

    def test_every_rule_cites_a_spec_section(self):
        assert all(r.spec_ref for r in RULES.values())


class TestClassACannotBeExcepted:
    """The central refusal. Not applied at check time -- refused at load."""

    def test_a_record_naming_a_class_a_rule_does_not_parse(self):
        yaml = """
        double_discount:
          condition: terminal_value_from_discounted_flow
          reason: long_duration_asset
          detail: we know, it is fine
          author: Someone
          date: 2026-08-31
          expiry: 2027-08-31
        """
        with pytest.raises(ExceptionError) as exc:
            load_exceptions(yaml)
        assert "Class A" in str(exc.value)
        assert "Fix the model, not the gate" in str(exc.value)

    @pytest.mark.parametrize("rule_id", [r.id for r in by_class(CLASS_A)])
    def test_no_class_a_rule_anywhere_accepts_a_record(self, rule_id):
        yaml = (f"k:\n  condition: {rule_id}\n  reason: pre_revenue\n"
                f"  detail: d\n  author: a\n  date: 2026-01-01\n  expiry: 2027-01-01\n")
        with pytest.raises(ExceptionError, match="Class A"):
            load_exceptions(yaml)

    def test_a_class_a_finding_is_never_satisfied_even_holding_a_record(self):
        """Belt and braces: if one somehow existed, it would still not satisfy."""
        smuggled = ExceptionRecord(
            key="smuggled", rule=rule("terminal_value_share"), measured=None,
            reason="pre_revenue", detail="d", author="a",
            declared=date(2026, 1, 1), expiry=date(2099, 1, 1))
        finding = Finding(rule=rule("real_growth_on_nominal_flows"),
                          detail="real g on nominal flows", exception=smuggled)
        assert finding.satisfied(TODAY) is False

    def test_apply_exceptions_does_not_attach_to_class_a_findings(self):
        records = load_exceptions(LONG_DURATION)
        findings = [Finding(rule("terminal_value_from_discounted_flow"), "d"),
                    Finding(rule("terminal_value_share"), "TV share 86.8%")]
        attached = apply_exceptions(findings, records)
        assert attached[0].exception is None
        assert attached[1].exception is not None


class TestExceptionRecords:
    def test_a_well_formed_class_b_record_loads(self):
        records = load_exceptions(LONG_DURATION)
        record = records["tv_share_infra"]
        assert record.rule.id == "terminal_value_share"
        assert record.reason == "long_duration_asset"
        assert record.measured == Decimal("0.868")
        assert record.author == "Bob Liang"
        assert record.expiry == date(2027, 2, 28)

    @pytest.mark.parametrize("field", ["condition", "reason", "detail",
                                       "author", "date", "expiry"])
    def test_every_field_is_required(self, field):
        import yaml as pyyaml
        entry = pyyaml.safe_load(LONG_DURATION)["tv_share_infra"]
        entry.pop(field)
        with pytest.raises(ExceptionError, match="missing required field"):
            load_exceptions(pyyaml.safe_dump({"k": entry}))

    def test_expiry_absent_is_named_as_a_permanent_carve_out(self):
        import yaml as pyyaml
        entry = pyyaml.safe_load(LONG_DURATION)["tv_share_infra"]
        entry.pop("expiry")
        with pytest.raises(ExceptionError, match="permanent carve-out"):
            load_exceptions(pyyaml.safe_dump({"k": entry}))

    def test_the_reason_vocabulary_is_closed(self):
        yaml = LONG_DURATION.replace("long_duration_asset", "management_judgement")
        with pytest.raises(ExceptionError, match="closed vocabulary"):
            load_exceptions(yaml)
        assert EXCEPTION_REASONS == ("long_duration_asset", "pre_revenue",
                                     "regulated_concession")

    def test_expiry_must_be_after_the_declaration(self):
        yaml = LONG_DURATION.replace("expiry: 2027-02-28", "expiry: 2026-08-30")
        with pytest.raises(ExceptionError, match="not after its date"):
            load_exceptions(yaml)

    def test_a_missing_store_is_empty_not_an_error(self, tmp_path):
        assert load_exceptions(tmp_path / "nope") == {}

    def test_for_rule_prefers_the_latest_expiry(self):
        second = LONG_DURATION.replace("tv_share_infra", "tv_share_renewed").replace(
            "expiry: 2027-02-28", "expiry: 2028-02-28")
        records = load_exceptions(LONG_DURATION + second)
        assert for_rule(records, "terminal_value_share").key == "tv_share_renewed"
        assert for_rule(records, "wacc_growth_spread") is None


class TestExpiry:
    def test_a_live_exception_satisfies_a_class_b_finding(self):
        records = load_exceptions(LONG_DURATION)
        finding = apply_exceptions(
            [Finding(rule("terminal_value_share"), "TV share 86.8%")], records)[0]
        assert finding.satisfied(TODAY) is True

    def test_an_expired_exception_does_not(self):
        records = load_exceptions(LONG_DURATION)
        finding = apply_exceptions(
            [Finding(rule("terminal_value_share"), "TV share 86.8%")], records)[0]
        assert finding.satisfied(date(2027, 3, 1)) is False

    def test_an_expired_exception_is_still_reported_as_having_lapsed(self):
        records = load_exceptions(LONG_DURATION)
        finding = apply_exceptions(
            [Finding(rule("terminal_value_share"), "TV share 86.8%")], records)[0]
        rendered = finding.render(date(2027, 3, 1))
        assert "EXPIRED" in rendered and "2027-02-28" in rendered


class TestOnePassingState:
    def test_no_findings_passes(self):
        assert FindingSet(as_of=TODAY).passed is True

    def test_a_class_a_finding_blocks(self):
        s = FindingSet([Finding(rule("real_growth_on_nominal_flows"), "d")],
                       as_of=TODAY)
        assert s.passed is False and len(s.blocking) == 1

    def test_an_unexcepted_class_b_finding_blocks(self):
        s = FindingSet([Finding(rule("terminal_value_share"), "86.8%")], as_of=TODAY)
        assert s.passed is False

    def test_an_excepted_class_b_finding_passes_without_a_second_state(self):
        records = load_exceptions(LONG_DURATION)
        s = FindingSet(apply_exceptions(
            [Finding(rule("terminal_value_share"), "TV share 86.8%")], records),
            as_of=TODAY)
        assert s.passed is True
        assert s.blocking == []
        assert len(s.excepted) == 1

    def test_an_exception_is_published_not_merely_consumed(self):
        """6.5: the output carries the exception visibly."""
        records = load_exceptions(LONG_DURATION)
        s = FindingSet(apply_exceptions(
            [Finding(rule("terminal_value_share"),
                     "TV share 86.8%, above the 75% threshold")], records),
            as_of=TODAY)
        assert s.disclosures == [
            "Exception: `long_duration_asset` — TV share 86.8%, "
            "above the 75% threshold."]


class TestMeasurements:
    def test_a_measurement_never_blocks(self):
        s = FindingSet(measurements=[
            Measurement("Terminal value share", Decimal("86.75"), "%", "4.6",
                        Decimal("75"))], as_of=TODAY)
        assert s.passed is True

    def test_a_measurement_renders_on_a_passing_run(self):
        s = FindingSet(measurements=[
            Measurement("Terminal value share", Decimal("60.10"), "%", "4.6",
                        Decimal("75"))], as_of=TODAY)
        rendered = s.render()
        assert "reported every run, pass or fail" in rendered
        assert "60.10% (threshold 75%)" in rendered
