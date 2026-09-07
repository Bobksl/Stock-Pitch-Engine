"""Generate the three degraded Section 1 drafts from the clean one.

Each is the SMALLEST edit that trips exactly one rule, so the diff against
draft_avgo_section1.md is the statement of what the rule catches.
"""
import pathlib
import sys

FIX = pathlib.Path(sys.argv[1])
clean = (FIX / "draft_avgo_section1.md").read_text(encoding="utf-8")

HEADER = "<!-- DEGRADED FIXTURE. {why} -->\n"


def sub(text, old, new, count=1):
    assert text.count(old) == count, (text.count(old), old[:70])
    return text.replace(old, new)


# --- 1. banned_language ----------------------------------------------------
# One 6.1 adjective, in prose, changing nothing else.
banned = sub(
    clean,
    "Nearly half the profit is enterprise software, and any",
    "Nearly half the profit is world-class enterprise software, and any")
banned = HEADER.format(
    why="One 6.1 adjective inserted into the conclusion. Trips "
        "banned_language and nothing else.") + banned

# --- 2. unsupported_qualitative_claim --------------------------------------
# A pricing-power claim with no figure in its sentence. The draft has no such
# claim to strip, which is itself the point: an unsupported claim is something
# a drafter ADDS, so the degraded case adds one.
unsupported = sub(
    clean,
    "selling duration rather than seats.",
    "selling duration rather than seats. The software franchise also enjoys\n"
    "considerable pricing power over its installed base.")
unsupported = HEADER.format(
    why="A pricing-power claim added with no figure in its sentence. Trips "
        "unsupported_qualitative_claim and nothing else.") + unsupported

# --- 3. segment_profit_missing ---------------------------------------------
# The revenue-only mix: profit column, profit shares and profit anchors all
# removed together, so nothing is left dangling and only the 1.3 rule fires.
seg = clean
seg = sub(seg,
          "Semiconductor Solutions sells 57.69% [^M1] of the revenue\n"
          "and earns 50.56% [^M2] of the segment profit; Infrastructure Software sells\n"
          "42.31% [^M3] and earns 49.44% [^M4], on a 76.82% [^M5] segment operating margin\n"
          "against 57.60% [^M6]. Nearly half the profit is enterprise software, and any\n"
          "comparison drawn against semiconductor peers alone prices the smaller half of\n"
          "the earnings.",
          "Semiconductor Solutions sells 57.69% [^M1] of the revenue\n"
          "and Infrastructure Software sells 42.31% [^M3]. The semiconductor half is\n"
          "the larger of the two.")
seg = sub(seg,
          "| Segment | Revenue ($m) | Operating profit ($m) | Margin (%) |\n"
          "|---|---|---|---|\n"
          "| Semiconductor Solutions | 36,858 [^F11] | 21,232 [^F12] | 57.60 [^M6] |\n"
          "| Infrastructure Software | 27,029 [^F13] | 20,765 [^F14] | 76.82 [^M5] |",
          "| Segment | Revenue ($m) |\n"
          "|---|---|\n"
          "| Semiconductor Solutions | 36,858 [^F11] |\n"
          "| Infrastructure Software | 27,029 [^F13] |")
for key in ("F12", "F14"):
    start = seg.index(f"{key}: {{kind: fact")
    end = seg.index("\n", seg.index("Member}}", start)) + 1
    seg = seg[:start] + seg[end:]
for key in ("M2", "M4", "M5", "M6"):
    start = seg.index(f"{key}:  {{kind: model")
    seg = seg[:start] + seg[seg.index("\n", start) + 1:]
seg = HEADER.format(
    why="The segment mix shown revenue-only: profit column, profit shares and "
        "both segment-profit anchors removed together, so nothing dangles. "
        "Trips segment_profit_missing and nothing else.") + seg

for name, text in (("draft_avgo_banned_language.md", banned),
                   ("draft_avgo_unsupported_claim.md", unsupported),
                   ("draft_avgo_segment_profit_missing.md", seg)):
    (FIX / name).write_text(text, encoding="utf-8")
    print("wrote", name, len(text), "chars")
