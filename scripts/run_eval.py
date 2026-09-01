"""Retrieval eval (Audit R7) — measure trust in retrieval before building on it.

    python scripts/run_eval.py
    python scripts/run_eval.py --k 10 --detail 5
    python scripts/run_eval.py --question msft_cloud_drivers --show

Reports hit@k, recall@k and MRR over the labelled set in eval/questions.yaml,
plus the mean top-document share of the retrieved set — the measurement behind
Audit R4's per-entity retrieval quota.

`--show` prints what was actually retrieved for a question, which is how a
label gets checked: a miss is either a retrieval failure or a wrong label, and
only reading the chunks tells you which.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.retrieval.eval.harness import load_questions, run_eval    # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--questions", help="path to the labelled set")
    ap.add_argument("--k", type=int, default=10, help="retrieval depth")
    ap.add_argument("--detail", type=int, default=5,
                    help="k at which per-Item results and misses are listed")
    ap.add_argument("--question", help="run one question by id")
    ap.add_argument("--show", action="store_true",
                    help="print the retrieved chunks for each question")
    ap.add_argument("--min-hit-rate", type=float,
                    help="exit non-zero if hit@detail falls below this")
    args = ap.parse_args()

    questions = load_questions(args.questions)
    if args.question:
        questions = [q for q in questions if q.id == args.question]
        if not questions:
            raise SystemExit(f"no question with id {args.question!r}")

    report = run_eval(questions, k=args.k)
    print(report.render(k_detail=args.detail))

    if args.show:
        for result in report.results:
            print(f"\n=== {result.question.id}: {result.question.question}")
            print(f"    gold: {'; '.join(str(g) for g in result.question.gold)}")
            for i, c in enumerate(result.retrieved[:args.detail], 1):
                mark = "*" if result.question.relevant(c) else " "
                head = " ".join(c["content"].split())[:110]
                print(f"  {mark}{i:>2}. {c['ticker']} FY{c['fiscal_year']} "
                      f"{c.get('section_key') or c['section']} "
                      f"d={c['distance']:.4f}\n        {head}")

    if args.min_hit_rate is not None and report.hit_rate(args.detail) < args.min_hit_rate:
        print(f"\nFAIL: hit@{args.detail} = {report.hit_rate(args.detail):.1%} "
              f"< {args.min_hit_rate:.1%}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
