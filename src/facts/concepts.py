"""Module 11 — canonical concept -> XBRL tag resolution.

The map itself lives in config/concept_map.yaml so that changing how a number is
sourced is a reviewable diff rather than an edit buried in query code.

CLI:  python -m src.facts.concepts --list
      python -m src.facts.concepts --sync      (mirror the YAML into concept_map)
"""
from dataclasses import dataclass
from functools import lru_cache

import yaml

from src.config import PROJECT_ROOT

CONCEPT_MAP_PATH = PROJECT_ROOT / "config" / "concept_map.yaml"


class ConceptError(KeyError):
    """A concept was requested that the map does not define."""


@dataclass(frozen=True)
class Concept:
    name: str
    label: str
    unit: str
    period_type: str          # 'duration' | 'instant'
    tags: tuple[str, ...]     # qnames, highest priority first


@lru_cache(maxsize=1)
def _load(path: str | None = None) -> dict:
    with open(path or CONCEPT_MAP_PATH, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def axes() -> dict[str, str]:
    """Named dimension axes, e.g. {'segment': 'us-gaap:StatementBusinessSegmentsAxis'}."""
    return dict(_load()["axes"])


def qualifier_axes() -> dict[str, list[str]]:
    """Axes that qualify a segment amount rather than slicing it further.

    {axis_qname: [allowed member qnames]} — see the note in concept_map.yaml.
    """
    return {k: list(v) for k, v in (_load().get("qualifier_axes") or {}).items()}


def axis(name: str) -> str:
    try:
        return axes()[name]
    except KeyError:
        raise ConceptError(f"unknown axis {name!r}; known: {sorted(axes())}") from None


def concept(name: str, cik: int | None = None) -> Concept:
    """Resolve a concept, applying any per-filer override."""
    doc = _load()
    base = doc["concepts"].get(name)
    if base is None:
        raise ConceptError(f"unknown concept {name!r}; known: {sorted(doc['concepts'])}")

    override = (doc.get("overrides") or {}).get(cik, {}).get(name) if cik else None
    tags = (override or base)["tags"]
    return Concept(name=name, label=base["label"], unit=base["unit"],
                   period_type=base["period_type"], tags=tuple(tags))


def all_concepts() -> list[str]:
    return sorted(_load()["concepts"])


def sync_to_db() -> int:
    """Mirror the YAML into the concept_map table so resolution is joinable in SQL."""
    from src.db import get_conn

    doc = _load()
    rows = []
    for name, body in doc["concepts"].items():
        for priority, qname in enumerate(body["tags"]):
            taxonomy, _, tag = qname.partition(":")
            rows.append((name, None, taxonomy, tag, priority, body["label"]))
    for cik, concepts in (doc.get("overrides") or {}).items():
        for name, body in concepts.items():
            for priority, qname in enumerate(body["tags"]):
                taxonomy, _, tag = qname.partition(":")
                rows.append((name, int(cik), taxonomy, tag, priority, body.get("note")))

    with get_conn() as conn:
        conn.execute("TRUNCATE concept_map")
        with conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO concept_map (concept, cik, taxonomy, tag, priority, note)"
                " VALUES (%s, %s, %s, %s, %s, %s)", rows)
    return len(rows)


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--sync", action="store_true")
    a = ap.parse_args()

    if a.sync:
        print(f"{sync_to_db()} concept_map rows written")
    if a.list or not a.sync:
        print(f"axes: {axes()}\n")
        for name in all_concepts():
            c = concept(name)
            print(f"{name:28} {c.unit:<12} {c.period_type:<9} {len(c.tags)} tag(s)")
            for t in c.tags:
                print(f"    {t}")
