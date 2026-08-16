"""DuckDB access layer over the canonical Parquet tables. Zero LLM cost —
every tool query in sentinel/tools/impl.py routes through here.
"""
from pathlib import Path
import duckdb

PROCESSED_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "processed"

_TABLES = ["entities", "events", "entity_links", "labels"]


def get_connection() -> duckdb.DuckDBPyConnection:
    con = duckdb.connect(database=":memory:")
    for t in _TABLES:
        path = PROCESSED_DIR / f"{t}.parquet"
        if path.exists():
            con.execute(f"CREATE OR REPLACE VIEW {t} AS SELECT * FROM read_parquet('{path}')")
    return con


_CONN = None


def conn() -> duckdb.DuckDBPyConnection:
    global _CONN
    if _CONN is None:
        _CONN = get_connection()
    return _CONN


def reset_connection():
    global _CONN
    _CONN = None
