# `tsmc_model.xlsx` — the Phase 2 acceptance fixture

A TSMC DCF, the repository owner's own work, committed as the valuation
engine's acceptance test. It is a competent, well-organised model, which is
the point: the eight defects the engine must flag (Audit section 2) are the
kind that survive ordinary human review.

Recomputing it from its own inputs reproduces its published target of
**TWD 1,732.66** exactly. Correcting the terminal-value double-discount alone
moves the target to **TWD 2,359.34** — and reveals that terminal value is
86.8% of enterprise value, above the 75% threshold of framework 4.6. The
arithmetic error was partially masking a terminal-value-dominated model. Two
errors offsetting, landing in a believable range: the single case that
justifies a deterministic QC layer.

**Sanitised before commit.** `docProps/core.xml` carried the author's personal
email address and `customXml/` carried a tenant binding; this repository is
public. Both were stripped. Every cell — formulas and cached values alike — is
byte-identical to the original.
