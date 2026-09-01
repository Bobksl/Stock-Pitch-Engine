# Declared exceptions to Class B rules

One YAML record per accepted Class B breach (framework 6.5). Every field is
required, expiry included.

```yaml
tv_share_infra:
  condition: terminal_value_share      # a Class B rule id from src/qc/rules.py
  measured: 0.868
  reason: long_duration_asset          # closed vocabulary, see exceptions.py
  detail: TV share 86.8%, above the 75% threshold
  author: Bob Liang
  date: 2026-08-31
  expiry: 2027-02-28                   # required; no permanent carve-outs
```

**This directory is committed, unlike `data/external/`.** That is the point.
External records are git-ignored because they hold licensed terminal data;
exception records are the opposite — closed classification is what makes them
countable and reviewable, and a carve-out nobody can see in a diff is exactly
what this design exists to prevent.

A record naming a Class A rule will not load. Class A is correctness: the
figure is wrong or unverifiable, and neither is something an assertion fixes.
