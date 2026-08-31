"""Phase 0 exit criterion — one command, cited, end to end.

    python scripts/research_cli.py segments --ticker MSFT --years 5

Audit section 7: "pull any US filer's segment revenue and profit, 5 years, fully
cited, in one command."

`ingest` runs the whole chain for a filer that has never been touched: resolve
the ticker, fetch the filings, parse the instances, load the facts, reconcile
against SEC, segment the documents. `segments` renders the panel.

Every printed figure carries (accession, tag, period, member). Nothing here
computes a number except the margin and the segment sum, both in Decimal, both
from cited inputs — framework P1/P3.
"""
import argparse
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.db import get_conn                                    # noqa: E402
from src.facts.api import get_segment_panel, pretty_member     # noqa: E402


def resolve_cik(ticker: str) -> int:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT cik FROM companies WHERE ticker = %s", (ticker.upper(),)).fetchone()
    if not row or row[0] is None:
        raise SystemExit(
            f"{ticker.upper()} is not in the database. Ingest it first:\n"
            f"    python scripts/research_cli.py ingest --ticker {ticker.upper()}")
    return row[0]


def cmd_ingest(args) -> int:
    from src.edgar.fetch import fetch_company
    from src.edgar.reconcile import reconcile_filing
    from src.facts.store import store_companyfacts, store_filing_facts
    from src.segment import segment_html

    print(f"[1/5] fetching {args.ticker} {args.form} filings from EDGAR")
    fetched = fetch_company(args.ticker, forms=(args.form,), years=args.years)
    for f in fetched:
        print(f"      {f['accession']}  period {f['period_end']}  {f['bytes']/1e6:.1f} MB")

    print("[2/5] parsing inline XBRL and loading facts")
    for f in fetched:
        s = store_filing_facts(f["accession"])
        print(f"      {s['accession']}  FY{s['fy']}  {s['facts']:,} facts "
              f"({s['dimensional']:,} dimensional)")

    print("[3/5] loading SEC companyfacts (reconciliation oracle)")
    cik = resolve_cik(args.ticker)
    print(f"      {store_companyfacts(cik)['facts']:,} consolidated rows")

    print("[4/5] reconciling parsed facts against SEC")
    for f in fetched:
        r = reconcile_filing(f["accession"])          # raises on any mismatch
        print(f"      {r}")

    print("[5/5] Item-anchoring the documents")
    with get_conn() as conn:
        doc_ids = [r[0] for r in conn.execute(
            "SELECT doc_id FROM documents WHERE cik = %s AND format = 'html' ORDER BY doc_id",
            (cik,))]
    for doc_id in doc_ids:
        print(f"      doc_id {doc_id}: {len(segment_html(doc_id))} Items")

    print(f"\n{args.ticker.upper()} ready. Now run:  "
          f"python scripts/research_cli.py segments --ticker {args.ticker.upper()}")
    return 0


def cmd_segments(args) -> int:
    cik = resolve_cik(args.ticker)
    as_of = date.fromisoformat(args.as_of) if args.as_of else None
    panel = get_segment_panel(cik, years=args.years, as_of=as_of)

    if not panel.periods:
        raise SystemExit(f"no segment data for {args.ticker.upper()}")

    basis = f"as filed on or before {as_of}" if as_of else "current basis (restatements applied)"
    print(f"\n{args.ticker.upper()}  segment revenue and operating profit  ·  {basis}")
    print(f"axis: {panel.axis}\n")

    failures = 0
    for _, period_end in panel.periods:
        print(f"  fiscal year ended {period_end}")
        print(f"    {'segment':<38} {'revenue':>18} {'op profit':>18} {'margin':>8}")
        for member in panel.members():
            cell = panel.cells.get((period_end, member))
            if not cell:
                continue
            rev, op, margin = cell.value("revenue"), cell.value("operating_income"), cell.margin
            print(f"    {pretty_member(member):<38} {rev or 0:>18,} {op or 0:>18,} "
                  f"{'' if margin is None else f'{margin:>7.1%}'}")

        total = panel.consolidated.get((period_end, "revenue"))
        seg_sum = panel.segment_sum(period_end, "revenue")
        ok = panel.reconciles(period_end, "revenue")
        failures += 0 if ok else 1
        print(f"    {'sum of segments':<38} {seg_sum or 0:>18,}")
        print(f"    {'consolidated (as reported)':<38} "
              f"{total.value if total else 0:>18,}   reconciles={ok}")

        if args.cite:
            print("    citations:")
            for member in panel.members():
                cell = panel.cells.get((period_end, member))
                if not cell:
                    continue
                for name, f in sorted(cell.facts.items()):
                    print(f"      {name:<17} {f.citation}")
            if total:
                print(f"      {'consolidated':<17} {total.citation}")
        print()

    if failures:
        print(f"FAIL: {failures} period(s) do not reconcile", file=sys.stderr)
        return 1
    print(f"OK: segments reconcile to the consolidated total in all "
          f"{len(panel.periods)} periods")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command", required=True)

    ing = sub.add_parser("ingest", help="fetch, parse, reconcile and segment a filer")
    ing.add_argument("--ticker", required=True)
    ing.add_argument("--form", default="10-K")
    ing.add_argument("--years", type=int, default=5)
    ing.set_defaults(func=cmd_ingest)

    seg = sub.add_parser("segments", help="segment revenue and operating profit, cited")
    seg.add_argument("--ticker", required=True)
    seg.add_argument("--years", type=int, default=5)
    seg.add_argument("--as-of", help="point-in-time view: YYYY-MM-DD")
    seg.add_argument("--cite", action="store_true", help="print the citation for every figure")
    seg.set_defaults(func=cmd_segments)

    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
