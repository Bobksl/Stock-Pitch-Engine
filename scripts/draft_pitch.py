"""Phase 3 exit criterion — Sections 1 and 2, drafted and gated in one command.

    python scripts/draft_pitch.py AVGO --sections 1,2 --qc

Unlike phases 0-2 there is no published answer to reproduce here. Phase 0 pulled
a segment panel, phase 1 caught a corrupted figure, phase 2 reproduced TWD
1,732.66. A narrative section has no equivalent, so this command tests two
things instead:

  VERIFIABILITY -- every figure in the emitted draft resolves to a fact, a
  model cell or a declared external record, is from the latest filed period,
  and the five exhibits 1.5 and 2.6 require are all present. A draft carrying
  no figures would satisfy "everything resolves" trivially, which is why the
  exhibits are part of the criterion.

  DETECTION -- the degraded drafts in tests/fixtures each trip exactly one 1.6
  or 2.7 rule. That half lives in the acceptance test rather than here.

The comp set is passed in and approved, never inferred: 2.3 auto-PROPOSES from
the type field and requires a human to approve, with a written justification
per member. `--comp-set` points at that approved YAML.
"""
import argparse
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import yaml                                                    # noqa: E402

from src.pitch.compset import (                                # noqa: E402
    CompSet,
    CompSetMember,
    comp_set_type_finding,
)
from src.pitch.draft import render                             # noqa: E402
from src.pitch.overview import Section1Evidence                # noqa: E402
from src.pitch.section2 import Section2Evidence                # noqa: E402
from src.qc.prose_rules import prose_findings                  # noqa: E402
from src.qc.report import verify_draft                         # noqa: E402

TEMPLATE = """# {company} - Company and Industry Overview

## Section 1 - Company Overview

**Conclusion.** The type field is {verdict}. {type_sentence}

Revenue reached {revenue} against {revenue_prior} the year before, a
{revenue_growth} increase. Operating income of {operating_income} is
{operating_margin} of revenue, and gross profit of {gross_profit} is
{gross_margin}. Research and development ran at {research_and_development}, or
{rd_intensity} of revenue, and share-based compensation of
{share_based_compensation} is {sbc_intensity} and a real cost against reported
profit. Operating cash flow of {operating_cash_flow} less capital expenditure of
{capex} leaves free cash flow of {free_cash_flow}, a {fcf_margin} margin.

### Segment mix

{segment_mix}

### Margin history

{margin_history}

### KPI snapshot

{kpi_snapshot}

## Section 2 - Industry Overview

**Conclusion.** {structural_conclusion} {profit_capture_conclusion}

### Industry panel

{industry_panel}

### Relative growth and margin

{relative_growth}

### Peer drawdown

{peer_drawdown}
"""


def load_comp_set(path, type_field):
    doc = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    members = tuple(
        CompSetMember(
            ticker=m["ticker"], cik=int(m["cik"]),
            tiers=frozenset(m["tiers"]), covers_type=m["covers_type"],
            justification=m["justification"], approved_by=m["approved_by"],
            approved_on=(date.fromisoformat(m["approved_on"])
                         if isinstance(m["approved_on"], str)
                         else m["approved_on"]))
        for m in doc["members"])
    return CompSet(members=members, type_field=type_field,
                   structural_conclusion=doc["structural_conclusion"],
                   profit_capture_conclusion=doc["profit_capture_conclusion"])


def build(ticker, comp_set_path, *, period_end, prior_period_end,
          calendar_year, kpi_group, gics, benchmark):
    from src.db import get_conn
    with get_conn() as conn:
        row = conn.execute("SELECT cik FROM companies WHERE ticker = %s",
                           (ticker.upper(),)).fetchone()
    if not row or row[0] is None:
        raise SystemExit(f"{ticker} is not ingested. Run research_cli.py ingest")

    section1 = Section1Evidence.build(row[0], period_end, prior_period_end,
                                      kpi_group=kpi_group, gics=gics)
    comp_set = load_comp_set(comp_set_path, section1.type_field)
    section2 = Section2Evidence.build(comp_set, calendar_year,
                                      target=(ticker.upper(), row[0]),
                                      benchmark=benchmark)

    figures = section1.figures() | section2.figures()
    blocks = {
        "segment_mix": section1.segment_mix_table(figures),
        "margin_history": section1.margin_history_table(figures),
        "kpi_snapshot": section1.kpi_snapshot_table(figures),
        "industry_panel": section2.industry_panel_table(figures),
        "relative_growth": section2.relative_growth_table(figures),
        "peer_drawdown": section2.drawdown_table(figures),
    }
    tf = section1.type_field
    prose = TEMPLATE.format(
        company=ticker.upper(), verdict=tf.verdict.upper(),
        type_sentence=(
            f"{tf.dominant_by_revenue} leads revenue and "
            f"{tf.dominant_by_profit} leads profit, so section 2 covers "
            f"{'both types' if tf.requires_both_types else 'the dominant type'}."),
        structural_conclusion=comp_set.structural_conclusion,
        profit_capture_conclusion=comp_set.profit_capture_conclusion,
        **{k: "{" + k + "}" for k in figures},
        **{k: "{" + k + "}" for k in blocks})

    cited = {n: f for n, f in figures.items()
             if "{" + n + "}" in prose
             or any(f"[^{f.marker}]" in b for b in blocks.values())}
    cells = dict(section1.cells) | dict(section2.cells) | dict(section2.panel.cells)
    return section1, section2, render(prose, cited, blocks=blocks, cells=cells)


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("ticker")
    ap.add_argument("--sections", default="1,2")
    ap.add_argument("--comp-set", default="config/comp_sets/avgo.yaml")
    ap.add_argument("--period-end", default="2025-11-02")
    ap.add_argument("--prior-period-end", default="2024-11-03")
    ap.add_argument("--calendar-year", type=int, default=2025)
    ap.add_argument("--kpi-group", default="semiconductors")
    ap.add_argument("--gics", default="Semiconductors")
    ap.add_argument("--benchmark", default="SPY")
    ap.add_argument("--qc", action="store_true", help="run the gate and exit non-zero on failure")
    ap.add_argument("--out", help="write the draft here")
    args = ap.parse_args()

    if args.sections != "1,2":
        raise SystemExit("phase 3 drafts sections 1 and 2 together")

    section1, section2, drafted = build(
        args.ticker, args.comp_set,
        period_end=date.fromisoformat(args.period_end),
        prior_period_end=date.fromisoformat(args.prior_period_end),
        calendar_year=args.calendar_year, kpi_group=args.kpi_group,
        gics=args.gics, benchmark=args.benchmark)

    markdown = drafted.markdown()
    if args.out:
        Path(args.out).write_text(markdown, encoding="utf-8")
        print(f"wrote {args.out} ({len(markdown):,} chars)")

    if not args.qc:
        print(markdown)
        return 0

    from src.qc.anchors import parse_index
    from src.qc.claims import extract_claims

    report = verify_draft(markdown)
    print(report.render())

    prose = prose_findings(markdown, extract_claims(markdown),
                           parse_index(markdown))
    type_finding = comp_set_type_finding(section2.comp_set)
    if type_finding:
        prose.append(type_finding)
    if prose:
        print("\nPROSE AND COMP-SET RULES")
        print("-" * 72)
        for finding in prose:
            print("  " + finding.render().replace("\n", "\n  "))

    print(f"\nEXHIBITS: {len(section2.panel.members)} panel members, "
          f"{len(section2.panel.excluded)} excluded, "
          f"{len(section2.windows)} stress window(s)")

    return 0 if (report.passed and not prose) else 1


if __name__ == "__main__":
    raise SystemExit(main())
