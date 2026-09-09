"""P3.8 — framework 2.8: the industry primer, versioned and content-addressed.

    "Industry work is cached as a versioned primer, reusable across names in
     the same sector, refreshed quarterly. Pitches reference a primer version.
     Saves duplicated effort and enforces internal consistency across your
     coverage."

The version is a digest of the content, not a counter
-----------------------------------------------------
`semiconductors@2025Q4#a1b2c3d4e5f6`. Two sessions deriving the same industry
work land on the same version; editing one conclusion produces a different one;
and a pitch that cites a version names something a reader can verify rather
than a label someone can reassign. `load_primer` re-derives the digest and
refuses a file whose stored version does not match its content, which is the
silent re-label that content addressing exists to prevent.

The creation date is deliberately outside the digest. Re-deriving the same
industry work IS the same primer, and a timestamp in the hash would make every
re-run a new version and defeat the point.

The cache boundary, which is the real decision
----------------------------------------------
Structure is shared; relative position is not.

A primer carries the comp set with its tiers and justifications, the
period-alignment decisions including who was excluded and why, and the 2.5c-g
structural conclusions. Those are properties of an INDUSTRY and reusing them
across names in that industry is the whole point.

It refuses to carry 2.5h's relative position -- "company growth minus
peer-median growth". That is a statement about one company. Caching it into a
sector primer would carry one name's conclusion silently onto the next pitch in
the same sector, which is the opposite of the consistency 2.8 is for. The
refusal is a hard error rather than a convention, because a convention here
fails quietly and looks like reuse.

Expiry blocks
-------------
2.8 says refreshed quarterly. A primer is live through the end of the quarter
FOLLOWING its own: dying the instant its own quarter ends would leave no window
in which to refresh it, and a second quarter of runway is a judgement call
stated once here. Reuse past that raises rather than warning -- 6.5 has exactly
one passing state, and a stale primer is either usable or it is not.
"""
import hashlib
import json
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

import yaml

from src.config import PROJECT_ROOT

DEFAULT_ROOT = PROJECT_ROOT / "data" / "primers"

#: Characters of digest in a version string.
DIGEST_CHARS = 12

#: Quarters a primer stays usable, counting its own. Two means "its own quarter
#: plus one to refresh in"; see the module docstring.
LIVE_QUARTERS = 2


class PrimerError(ValueError):
    """A primer is malformed, expired, or carrying something it must not."""


def quarter_of(day: date) -> str:
    return f"{day.year}Q{(day.month - 1) // 3 + 1}"


def _next_quarter(quarter: str) -> str:
    year, q = int(quarter[:4]), int(quarter[-1])
    return f"{year + 1}Q1" if q == 4 else f"{year}Q{q + 1}"


def _quarter_end(quarter: str) -> date:
    year, q = int(quarter[:4]), int(quarter[-1])
    month = q * 3
    last = {3: 31, 6: 30, 9: 30, 12: 31}[month]
    return date(year, month, last)


@dataclass(frozen=True)
class Primer:
    """One industry's cached work, addressed by what it says."""

    industry_key: str
    quarter: str
    #: Approved comp-set members, each already tiered and justified (2.3).
    comp_set: list[dict[str, Any]]
    #: 2.5c -- what firms compete ON.
    structural_conclusion: str
    #: 2.5d -- where profit sits in the value chain, and whether it is moving.
    profit_capture_conclusion: str
    #: 2.4 -- who shares a calendar column and who was excluded, with reasons.
    alignment: dict[str, Any] = field(default_factory=dict)
    created_on: date = field(default_factory=date.today)
    #: Present only to be refused. See __post_init__.
    relative_position: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        if self.relative_position:
            raise PrimerError(
                "a primer must not carry relative position. 2.5h's company "
                "growth minus peer-median growth is a statement about ONE "
                "company, and caching it into a sector primer carries that "
                "name's conclusion silently onto the next pitch in the sector")
        if not self.industry_key:
            raise PrimerError("a primer needs an industry key to be reusable by")
        if not self.comp_set:
            raise PrimerError(
                "a primer with an empty comp set caches nothing worth reusing")
        if not self.structural_conclusion.strip():
            raise PrimerError(
                "no structural conclusion (2.5c): what firms compete ON is the "
                "part of the industry work that transfers between names")
        if not self.profit_capture_conclusion.strip():
            raise PrimerError("no profit capture conclusion (2.5d)")

    # -- identity -----------------------------------------------------------
    def content(self) -> dict[str, Any]:
        """Exactly what the digest covers. Creation date deliberately absent."""
        return {
            "industry_key": self.industry_key,
            "quarter": self.quarter,
            "comp_set": self.comp_set,
            "structural_conclusion": self.structural_conclusion,
            "profit_capture_conclusion": self.profit_capture_conclusion,
            "alignment": self.alignment,
        }

    @property
    def digest(self) -> str:
        payload = json.dumps(self.content(), sort_keys=True, default=str)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:DIGEST_CHARS]

    @property
    def version(self) -> str:
        return f"{self.industry_key}@{self.quarter}#{self.digest}"

    # -- expiry -------------------------------------------------------------
    @property
    def expires_after(self) -> str:
        """The last quarter in which this primer may be used."""
        quarter = self.quarter
        for _ in range(LIVE_QUARTERS - 1):
            quarter = _next_quarter(quarter)
        return quarter

    def live(self, as_of: date | None = None) -> bool:
        return (as_of or date.today()) <= _quarter_end(self.expires_after)

    def require_live(self, as_of: date | None = None) -> "Primer":
        """The primer, or a hard failure. Never a warning."""
        if not self.live(as_of):
            raise PrimerError(
                f"primer {self.version} expired after {self.expires_after} and "
                f"2.8 refreshes quarterly. Re-derive the industry work; a "
                f"stale primer is either usable or it is not")
        return self

    def render(self) -> str:
        lines = [f"Primer {self.version}",
                 f"  usable through {self.expires_after}, created "
                 f"{self.created_on}",
                 f"  comp set ({len(self.comp_set)}): "
                 f"{', '.join(m['ticker'] for m in self.comp_set)}",
                 f"  structure:      {self.structural_conclusion}",
                 f"  profit capture: {self.profit_capture_conclusion}"]
        for label, why in (self.alignment.get("excluded") or {}).items():
            lines.append(f"  excluded {label}: {why}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------

def save_primer(primer: Primer, *, root: Path | str | None = None) -> Path:
    """Write to data/primers/<industry>/<quarter>.yaml, version stamped in."""
    directory = Path(root or DEFAULT_ROOT) / primer.industry_key
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{primer.quarter}.yaml"
    body = {"version": primer.version, "created_on": primer.created_on,
            **primer.content()}
    path.write_text(
        yaml.safe_dump(body, sort_keys=True, allow_unicode=True, width=88),
        encoding="utf-8")
    return path


def load_primer(path: Path | str) -> Primer:
    """Read a primer back, re-deriving the digest and refusing a mismatch."""
    loaded = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    stated = loaded.pop("version", None)
    created = loaded.pop("created_on", None)
    if isinstance(created, str):
        created = date.fromisoformat(created)

    primer = Primer(created_on=created or date.today(), **loaded)
    if stated and stated != primer.version:
        raise PrimerError(
            f"{path}: stored version {stated} does not match its content, "
            f"which digests to {primer.version}. The file was edited without "
            f"re-deriving the version, and a primer that can be re-labelled "
            f"without changing its name is not a version at all")
    return primer
