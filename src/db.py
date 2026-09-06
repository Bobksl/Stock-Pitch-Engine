"""psycopg3 connection helper with pgvector type registration.

The driver is imported inside `get_conn`, not at module scope. Modules across
`src/` import `get_conn` at their own import time while the DB-backed path is
optional, and every DB-backed test is guarded by a `try/except -> skip` probe.
A module-scope `import psycopg` put the driver ahead of those guards: without
it installed, collection died before a single guard could run. The same reason
`facts/concepts.py`, `edgar/html_text.py` and `edgar/ixbrl.py` defer this import.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from src.config import PG

if TYPE_CHECKING:
    import psycopg


def get_conn() -> psycopg.Connection:
    """New autocommit connection with vector type registered."""
    import psycopg
    from pgvector.psycopg import register_vector

    conn = psycopg.connect(**PG, autocommit=True)
    register_vector(conn)
    return conn


def ping() -> str:
    with get_conn() as conn:
        return conn.execute("SELECT version()").fetchone()[0]


if __name__ == "__main__":
    print(ping())
