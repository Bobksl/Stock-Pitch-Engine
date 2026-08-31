"""P1.2 — declared external sources, the third and last provenance class.

Some figures have no facts-table row by construction: consensus estimates
(framework 3.5 variant perception is *definitionally* impossible without them),
market prices, peer multiples, beta inputs. Hard-failing them would make the
verifier unusable on a real pitch; accepting them on the author's word would
make it a rubber stamp.

So an external figure resolves only against a **declared record** carrying its
value, unit, source and as-of date, and the record's `kind` must come from a
closed vocabulary of things the facts table cannot answer. That restriction is
the whole point. Without it this class is an allowlist: anything failing the
facts check could be re-declared as external and pass. With it, a figure that
XBRL could have supplied -- segment revenue, operating income -- is rejected at
declaration time and must go back to the facts table.

    KIND_CONSENSUS      forward estimates (BEst and equivalents)
    KIND_MARKET_PRICE   share price, market capitalisation, index level
    KIND_BETA_INPUT     regression inputs and peer betas
    KIND_PEER_MARKET    peer multiples and market-derived comparables
    KIND_MACRO          rates, GDP, FX, inflation series

Redistribution boundary
-----------------------
Bloomberg-derived values are licensed, and this repository is public. The store
therefore lives under a git-ignored directory: it is auditable on the machine
that runs the pitch, and it never reaches GitHub. That is a real weakening of
the "reviewable diff" property that concept_map.yaml enjoys, and it is the
deliberate cost of not committing terminal data to a public repo. The QC report
prints every external record it relied on so the trade is at least visible at
the point of use.
"""
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import yaml

from src.config import PROJECT_ROOT

KIND_CONSENSUS = "consensus_estimate"
KIND_MARKET_PRICE = "market_price"
KIND_BETA_INPUT = "beta_input"
KIND_PEER_MARKET = "peer_market_data"
KIND_MACRO = "macro_series"

#: Closed vocabulary. Everything here is a figure the XBRL facts table cannot
#: answer even in principle. Adding a kind is a reviewable change to this file
#: and should be argued the same way a new concept-map tag is argued.
EXTERNAL_KINDS = (KIND_CONSENSUS, KIND_MARKET_PRICE, KIND_BETA_INPUT,
                  KIND_PEER_MARKET, KIND_MACRO)

DEFAULT_STORE = PROJECT_ROOT / "data" / "external"

_REQUIRED = ("kind", "value", "unit", "source", "as_of")


class ExternalError(ValueError):
    """An external record is missing, malformed, or declares an illegal kind."""


@dataclass(frozen=True)
class ExternalRecord:
    """A figure from outside EDGAR, with the provenance that makes it usable."""

    key: str
    kind: str
    value: Decimal
    unit: str
    source: str                    # 'Bloomberg BEst', 'NYSE close', ...
    as_of: date
    note: str | None = None
    ticker: str | None = None

    @property
    def citation(self) -> str:
        return f"ext:{self.key} | {self.kind} | {self.source} | as of {self.as_of}"


def _parse(key: str, entry: Any) -> ExternalRecord:
    if not isinstance(entry, dict):
        raise ExternalError(f"external record {key!r}: entry must be a mapping")
    missing = [f for f in _REQUIRED if entry.get(f) is None]
    if missing:
        raise ExternalError(
            f"external record {key!r}: missing required field(s) {', '.join(missing)}")
    kind = entry["kind"]
    if kind not in EXTERNAL_KINDS:
        raise ExternalError(
            f"external record {key!r}: kind {kind!r} is not an external-only "
            f"quantity. Legal kinds are {EXTERNAL_KINDS}. A figure the facts "
            f"table can answer must be cited from the facts table.")
    as_of = entry["as_of"]
    if isinstance(as_of, str):
        as_of = date.fromisoformat(as_of)
    return ExternalRecord(
        key=key, kind=kind, value=Decimal(str(entry["value"])), unit=str(entry["unit"]),
        source=str(entry["source"]), as_of=as_of, note=entry.get("note"),
        ticker=entry.get("ticker"))


def load_records(source: str | Path | None = None) -> dict[str, ExternalRecord]:
    """Every declared external record, keyed by record key.

    `source` may be a YAML string, a file, or a directory of `*.yaml` files.
    A missing store is not an error: it yields {}, and the resulting failure is
    reported per figure ("no external record named X") rather than as one
    opaque error about a missing directory.
    """
    if source is None:
        source = DEFAULT_STORE

    texts: list[str] = []
    if isinstance(source, str) and "\n" in source:
        texts.append(source)
    else:
        path = Path(source)
        if path.is_dir():
            texts.extend(p.read_text(encoding="utf-8")
                         for p in sorted(path.glob("*.yaml")))
        elif path.is_file():
            texts.append(path.read_text(encoding="utf-8"))

    records: dict[str, ExternalRecord] = {}
    for text in texts:
        try:
            loaded = yaml.safe_load(text) or {}
        except yaml.YAMLError as exc:
            raise ExternalError(f"external store is not valid YAML: {exc}") from None
        if not isinstance(loaded, dict):
            raise ExternalError("external store must be a mapping of key -> record")
        # Accept either a bare mapping or one nested under `records:`.
        entries = loaded.get("records") if "records" in loaded else loaded
        for key, entry in (entries or {}).items():
            records[str(key)] = _parse(str(key), entry)
    return records
