"""P3.7 — framework 2.3: the comp set, in two tiers, manually approved.

    "Direct competitors -- same customer, same buying decision, comparable
     scale -- used by the structural analysis (2.5).
     Valuation reference -- similar economics, growth, margin profile -- used
     by section 4 comps.
     Overlapping but distinct. A 10x size gap with a different customer base
     means NOT a direct competitor. Auto-proposed from the type field and
     revenue-model tags; MANUALLY APPROVED, with written justification per
     member."

Where 2.7's five conditions live
-------------------------------
Spec v1.3 split them, and this module is where the split becomes real. Three
are construction-time invariants and have no rule, because the defect cannot be
built: a member without a tier, a member without a justification, and a section
without its structural and profit-capture conclusions all fail to CONSTRUCT.
Nothing unbuildable can reach the gate, which is strictly stronger than a rule
that checks afterwards, and it is the same trick `exceptions.py` uses to make
Class A unexceptionable.

The two that remain are gate rules. `comp_set_not_type_justified` is answered
here; `sizing_without_derivation` belongs with market sizing (2.5a/b) and is
not this module's.

Why the type check is Class A and not Class B
---------------------------------------------
It reads like model shape -- an unusual comp set, not a wrong one -- and Class
B is the tempting answer. But it is C1, the join key the rest of the pitch
hangs off, and the test v1.3 states in 6.5 settles it: no reason in the closed
exception vocabulary (`long_duration_asset`, `pre_revenue`,
`regulated_concession`) could ever excuse comparing a company against the wrong
industry. Class B would hand it a door that opens onto nothing.

Broadcom is the live case. Its type field is `contested` -- 50.56% of profit in
semiconductors against 49.44% in infrastructure software -- so a comp set of
semiconductor names alone prices the smaller half of the earnings, and this
rule is what stops it.
"""
from dataclasses import dataclass
from datetime import date

from src.qc.findings import Finding
from src.qc.rules import rule
from src.valuation.comps import MINIMUM_COMP_SET

#: Same customer, same buying decision, comparable scale. Feeds 2.5 and the
#: 2.4 industry panel.
TIER_DIRECT = "direct_competitor"
#: Similar economics, growth and margin profile. Feeds section 4 comps.
TIER_VALUATION = "valuation_reference"

TIERS = (TIER_DIRECT, TIER_VALUATION)

#: A justification shorter than this is a label, not a reason. 2.3 asks for a
#: WRITTEN justification per member, and a field that accepts "competitor"
#: enforces nothing at all. The number is arbitrary and the intent is not.
MIN_JUSTIFICATION_CHARS = 25


class CompSetError(ValueError):
    """A comp set or a member of one cannot be built as described.

    Raised rather than reported: these are 2.7's construction-time invariants,
    and the point of them is that the defective object never exists.
    """


@dataclass(frozen=True)
class CompSetMember:
    """One approved peer, its tier(s), and why it is here.

    Frozen and validated on construction, so a member circulating anywhere in
    the pipeline has already been justified and approved.
    """

    ticker: str
    cik: int
    tiers: frozenset[str]
    #: Which side of the target's type field this member speaks to. For a
    #: contested type field the set must reach every side; see
    #: `comp_set_type_finding`.
    covers_type: str
    justification: str
    approved_by: str
    approved_on: date

    def __post_init__(self) -> None:
        if not self.tiers:
            raise CompSetError(
                f"{self.ticker}: no tier. 2.3 has exactly two, "
                f"{TIER_DIRECT!r} and {TIER_VALUATION!r}, and they are used by "
                f"different sections -- an untiered member has no consumer")
        if unknown := sorted(self.tiers - set(TIERS)):
            raise CompSetError(f"{self.ticker}: unknown tier(s) {unknown}")
        if not self.covers_type:
            raise CompSetError(
                f"{self.ticker}: covers_type is empty. C1 cannot check a comp "
                f"set against the type field if a member does not say which "
                f"part of the business it is a comp for")
        if len(" ".join(self.justification.split())) < MIN_JUSTIFICATION_CHARS:
            raise CompSetError(
                f"{self.ticker}: justification is {len(self.justification)} "
                f"characters. 2.3 requires a written justification per member; "
                f"a label is not a reason")
        if not self.approved_by:
            raise CompSetError(
                f"{self.ticker}: not approved. 2.3 auto-PROPOSES from the type "
                f"field and revenue-model tags, and requires a human to "
                f"approve. An unapproved member is a proposal")

    @property
    def is_direct(self) -> bool:
        return TIER_DIRECT in self.tiers

    @property
    def is_valuation_reference(self) -> bool:
        return TIER_VALUATION in self.tiers

    def render(self) -> str:
        tiers = "+".join(sorted(t.split("_")[0] for t in self.tiers))
        return (f"{self.ticker:<6} {tiers:<18} {self.covers_type:<26} "
                f"{self.justification}")


@dataclass(frozen=True)
class CompSet:
    """An approved comp set, plus the two 2.5 conclusions it must carry."""

    members: tuple[CompSetMember, ...]
    #: A `TypeField`; only `requires_both_types` and `shares` are read.
    type_field: object
    #: 2.5c. What firms compete ON -- price rivalry and feature rivalry produce
    #: entirely different margin trajectories.
    structural_conclusion: str
    #: 2.5d. Where in the value chain profit sits, and whether it is moving.
    profit_capture_conclusion: str

    def __post_init__(self) -> None:
        if not self.members:
            raise CompSetError("a comp set with no members is not a comp set")
        if len(" ".join(self.structural_conclusion.split())) < MIN_JUSTIFICATION_CHARS:
            raise CompSetError(
                "no structural conclusion. 2.7: a competitor list with no "
                "structural conclusion is a list, and 2.5c wants what firms "
                "compete ON, because price and feature rivalry produce "
                "different margin trajectories")
        if len(" ".join(self.profit_capture_conclusion.split())) < MIN_JUSTIFICATION_CHARS:
            raise CompSetError(
                "no profit capture conclusion. 2.5d asks where in the value "
                "chain profit sits and whether it is moving")

    # -- the tiers ----------------------------------------------------------
    @property
    def direct(self) -> tuple[CompSetMember, ...]:
        return tuple(m for m in self.members if m.is_direct)

    @property
    def valuation_reference(self) -> tuple[CompSetMember, ...]:
        return tuple(m for m in self.members if m.is_valuation_reference)

    def panel_members(self) -> dict[str, int]:
        """{ticker: cik} for the 2.4 industry panel -- the DIRECT tier.

        2.3 assigns the tiers to different consumers: direct competitors to the
        structural analysis, valuation references to section 4. Handing the
        panel the valuation tier would compare the target against companies
        chosen for their multiples.
        """
        return {m.ticker: m.cik for m in self.direct}

    @property
    def types_covered(self) -> set[str]:
        return {m.covers_type for m in self.members}

    @property
    def below_minimum(self) -> bool:
        """4.8's minimum is Class B and exceptionable, so this is reported for
        the gate to weigh rather than raised at construction."""
        return len(self.members) < MINIMUM_COMP_SET

    def render(self) -> str:
        lines = [f"Comp set ({len(self.members)} approved, "
                 f"{len(self.direct)} direct, "
                 f"{len(self.valuation_reference)} valuation reference)"]
        lines += ["  " + m.render() for m in self.members]
        lines.append(f"  structure:      {self.structural_conclusion}")
        lines.append(f"  profit capture: {self.profit_capture_conclusion}")
        return "\n".join(lines)


def comp_set_type_finding(comp_set: CompSet) -> Finding | None:
    """C1 / 2.7 — a comp set that does not cover what the type field requires.

    Only bites when the type field is contested or disagreed. When one segment
    demonstrably carries the company, a single-type comp set is the right
    answer rather than a lapse.
    """
    if not comp_set.type_field.requires_both_types:
        return None

    required = {s.label for s in comp_set.type_field.shares}
    missing = sorted(required - comp_set.types_covered)
    if not missing:
        return None

    return Finding(
        rule=rule("comp_set_not_type_justified"),
        detail=(f"the type field is {comp_set.type_field.verdict} and needs "
                f"comps for {sorted(required)}, but the approved set covers "
                f"only {sorted(comp_set.types_covered)} - nothing speaks to "
                f"{missing}. Framework 1.4h: GICS is the default, overridden "
                f"by profit-weighted reality, and a comp set drawn from the "
                f"GICS label alone prices the smaller half of the earnings"))
