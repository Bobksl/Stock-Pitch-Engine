"""P2.4 — the QC rule registry: every rule, and its class (framework 6.5).

**Every QC rule is Class A or Class B.**

- **Class A -- correctness.** The figure is wrong or unverifiable. Never
  exceptionable. No allowlist, no severity ladder, no override.
- **Class B -- model shape.** The model is unusual, not wrong. Satisfiable by
  a declared exception record (`exceptions.py`).

There remains exactly one passing state. Class B exists not because some
breaches matter less, but because a legitimately long-duration asset -- an
infrastructure concession, a pre-revenue biotech, anything carrying a fifteen
year explicit forecast -- can breach a shape heuristic honestly. A hard block
with no path would mean the system cannot value those names at all, and the
analyst routes around the system entirely. A reviewable exception is strictly
better than that.

The class lives on the rule, here, and not at the call site. That is what
makes "Class A is never exceptionable" a property of the data rather than a
discipline someone has to remember: `exceptions.py` refuses at load time to
build a record naming a Class A rule, so no code path exists in which a Class
A finding could consult one.

Numbering
---------
Two schemes exist for the same eight defects and they disagree, so the mapping
lives here and nowhere else. `DEFECTS` follows the eight-row exit-criterion
table, which is what the acceptance test asserts against. `AUDIT_FINDINGS`
maps the audit's own section 2 headings onto it -- the audit folds terminal
value share and the WACC-minus-g spread into a single "Finding 2", so every
later reference in that document is offset by one.

A note on completeness
----------------------
Two rules here were absent from framework 4.13 when Phase 2 began, and both
were added to the spec at v1.2 rather than carried as local extensions.

`stub_period_overstates_cash_flow` had no rule at all: the audit's section
2.10 mapping table asserts every one of its findings is caught by an existing
rule, but omits its own finding 6 (the stub), and 4.13's Class A list covered
nothing like it. The exit criterion requires the defect flagged and Class A,
so the claim was false rather than the rule merely unwritten. v1.2 states the
stub convention in 4.5 and adds the matching Class A rule.

`beta_not_derived` was folded into "WACC copied from a terminal". 4.4 states
the beta policy in its own right, and the two are separately detectable and
separately reported, so v1.2 lists them separately.
"""
from dataclasses import dataclass

#: The figure is wrong or unverifiable. Never exceptionable.
CLASS_A = "correctness"
#: The model is unusual, not wrong. Exceptionable by declared record.
CLASS_B = "model_shape"

CLASSES = (CLASS_A, CLASS_B)


class UnknownRule(KeyError):
    """A rule id that is not in the registry."""


@dataclass(frozen=True)
class Rule:
    """One QC rule. The class is a property of the rule, not of the caller."""

    id: str
    rule_class: str
    spec_ref: str
    title: str
    #: Exit-criterion defect number, where this rule is one of the eight.
    defect: int | None = None

    @property
    def exceptionable(self) -> bool:
        return self.rule_class == CLASS_B

    def __str__(self) -> str:
        label = "A" if self.rule_class == CLASS_A else "B"
        return f"[{label}] {self.id} ({self.spec_ref}) — {self.title}"


def _registry(*rules: Rule) -> dict[str, Rule]:
    seen: dict[str, Rule] = {}
    for rule in rules:
        if rule.rule_class not in CLASSES:
            raise ValueError(f"{rule.id}: unknown class {rule.rule_class!r}")
        if rule.id in seen:
            raise ValueError(f"duplicate rule id {rule.id!r}")
        seen[rule.id] = rule
    return seen


RULES: dict[str, Rule] = _registry(
    # ---------------------------------------------------------------- Class A
    Rule("llm_computed_arithmetic", CLASS_A, "4.13",
         "A figure was computed by the LLM rather than in Python"),
    Rule("wacc_not_derived", CLASS_A, "4.3",
         "WACC copied from a terminal rather than built from inputs"),
    Rule("beta_not_derived", CLASS_A, "4.4",
         "Beta taken from a terminal rather than computed and relevered",
         defect=5),
    Rule("equity_weight_not_market_cap", CLASS_A, "4.3",
         "Equity weight is not market capitalisation", defect=6),
    Rule("terminal_value_from_discounted_flow", CLASS_A, "4.13",
         "Terminal value computed from an already-discounted cash flow",
         defect=1),
    Rule("real_growth_on_nominal_flows", CLASS_A, "4.6",
         "A real growth rate applied to nominal cash flows", defect=4),
    Rule("stub_period_overstates_cash_flow", CLASS_A, "4.5",
         "A partial-period discount factor applied to a full period of cash flow",
         defect=7),
    Rule("scale_undeclared", CLASS_A, "6.4",
         "Unit or scale mismatch, or a scale that was never declared"),
    Rule("unresolvable_figure", CLASS_A, "6.4",
         "A figure resolving to no declared provenance class"),
    Rule("pairing_violation", CLASS_A, "4.8",
         "Numerator and denominator are not both pre- or both post-interest"),
    Rule("comp_definitions_inconsistent", CLASS_A, "4.8",
         "Comp metric definitions differ across peers"),
    Rule("scenarios_not_traceable", CLASS_A, "4.10",
         "Scenarios not traceable to named thesis pillars"),
    Rule("share_count_not_diluted", CLASS_A, "4.9",
         "Share count is not fully diluted"),
    Rule("target_reverse_engineered", CLASS_A, "4.9",
         "Target price reverse-engineered from a desired upside"),
    Rule("anchor_range_not_disclosed", CLASS_A, "4.8",
         "Implied target not shown under every peer anchor"),
    Rule("excel_python_divergence", CLASS_A, "4.12",
         "Excel recalculation disagrees with Python beyond tolerance (C11)"),
    Rule("figure_not_latest_period", CLASS_A, "6.3",
         "A figure is not from the latest filed period (C12)"),

    # ---------------------------------------------------------------- Class B
    Rule("terminal_value_share", CLASS_B, "4.6",
         "Terminal value exceeds 75% of enterprise value", defect=2),
    Rule("wacc_growth_spread", CLASS_B, "4.6",
         "WACC minus terminal growth is below 4 percentage points", defect=3),
    Rule("single_method_valuation", CLASS_B, "4.2",
         "Valuation rests on a single method without triangulation", defect=8),
    Rule("comp_set_below_minimum", CLASS_B, "4.8",
         "Comp set is below the minimum size"),
)


def rule(rule_id: str) -> Rule:
    """The registered rule, or a failure naming what was asked for."""
    try:
        return RULES[rule_id]
    except KeyError:
        raise UnknownRule(
            f"no QC rule {rule_id!r}. Adding a rule is a reviewable change to "
            f"src/qc/rules.py, argued the same way a spec section is argued."
        ) from None


#: Exit-criterion defect number -> rule id. The acceptance test asserts against
#: this, and it is the numbering used everywhere in Phase 2.
DEFECTS: dict[int, str] = {
    r.defect: r.id for r in RULES.values() if r.defect is not None}

#: The audit's own section 2 headings -> exit-criterion defect number. The
#: audit's "Finding 2" covers two distinct rules, which is where the offset
#: between the two schemes comes from.
AUDIT_FINDINGS: dict[int, tuple[int, ...]] = {
    1: (1,),           # 2.2 terminal value double-discounting
    2: (2, 3),         # 2.3 TV share AND the WACC-minus-g spread
    3: (4,),           # 2.4 real rate on nominal flows
    4: (5,),           # 2.5 beta from the terminal
    5: (6,),           # 2.6 equity weight
    6: (7,),           # 2.7 stub-period discounting
    7: (8,),           # 2.8 method concentration, folded into defect 8
    8: (8,),           # 2.9 structural gaps, folded into defect 8
}


def by_class(rule_class: str) -> tuple[Rule, ...]:
    return tuple(r for r in RULES.values() if r.rule_class == rule_class)
