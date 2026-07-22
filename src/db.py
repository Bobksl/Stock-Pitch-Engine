"""psycopg3 connection helper with pgvector type registration."""
import psycopg
from pgvector.psycopg import register_vector

from src.config import PG


def get_conn() -> psycopg.Connection:
    """New autocommit connection with vector type registered."""
    conn = psycopg.connect(**PG, autocommit=True)
    register_vector(conn)
    return conn


def ping() -> str:
    with get_conn() as conn:
        return conn.execute("SELECT version()").fetchone()[0]


if __name__ == "__main__":
    print(ping())
