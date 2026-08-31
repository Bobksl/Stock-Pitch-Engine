"""The numeric QC gate (Audit R5) — run it over a Markdown draft.

    python scripts/verify_draft.py tests/fixtures/draft_msft_golden.md \
        --externals tests/fixtures/external_test.yaml

Exit code 0 only when every figure resolved and no series is stale. Anything
else exits 1 and blocks publication: framework 5's "fail loudly", and the
standing decision that an unresolvable figure is a hard failure with no
allowlist and no severity ladder.

`--as-of` runs the whole check point-in-time (Audit G6): figures resolve against
what had been filed by that date, so a pitch backtested on a past date is
checked against what the market actually knew.

`--claims` lists what the extractor found without resolving anything, which is
the first thing to look at when a figure fails in a way you did not expect.
"""
import argparse
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.qc.claims import extract_claims            # noqa: E402
from src.qc.report import verify_draft              # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("draft", help="path to the Markdown draft")
    ap.add_argument("--as-of", help="point-in-time check: YYYY-MM-DD")
    ap.add_argument("--externals",
                    help="external record store (file or directory); "
                         "defaults to data/external/")
    ap.add_argument("--claims", action="store_true",
                    help="list extracted claims and exit, without resolving")
    args = ap.parse_args()

    md = Path(args.draft).read_text(encoding="utf-8")

    if args.claims:
        for c in extract_claims(md):
            print(f"  L{c.line:>3} {c.text:<24} {c.value:>22,f}  "
                  f"ulp={c.ulp:<12} {c.kind:<9} {c.scale_source:<13} "
                  f"[{c.anchor or '-'}]")
        return 0

    report = verify_draft(
        md,
        as_of=date.fromisoformat(args.as_of) if args.as_of else None,
        externals=args.externals)

    print(report.render())
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
