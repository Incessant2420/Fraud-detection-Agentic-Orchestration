"""SQLite-backed response cache keyed on sha256(model + prompt + tools_schema).
Ablations and reruns replay many identical calls; this makes reruns near-free
and is what lets the eval harness be re-run repeatedly without burning quota.
"""
import hashlib
import json
import sqlite3
from pathlib import Path


def cache_key(model: str, prompt: str, tools_schema: dict | list | None) -> str:
    schema_str = json.dumps(tools_schema, sort_keys=True) if tools_schema else ""
    h = hashlib.sha256()
    h.update(model.encode())
    h.update(b"\x00")
    h.update(prompt.encode())
    h.update(b"\x00")
    h.update(schema_str.encode())
    return h.hexdigest()


class ResponseCache:
    def __init__(self, db_path: str):
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(db_path)
        self._conn.execute(
            """CREATE TABLE IF NOT EXISTS response_cache (
                   key TEXT PRIMARY KEY,
                   model TEXT NOT NULL,
                   response_json TEXT NOT NULL,
                   prompt_tokens INTEGER,
                   completion_tokens INTEGER,
                   created_at TEXT NOT NULL DEFAULT (datetime('now'))
               )"""
        )
        self._conn.commit()
        self.hits = 0
        self.misses = 0

    def get(self, model: str, prompt: str, tools_schema=None) -> dict | None:
        key = cache_key(model, prompt, tools_schema)
        row = self._conn.execute(
            "SELECT response_json, prompt_tokens, completion_tokens FROM response_cache WHERE key = ?",
            (key,),
        ).fetchone()
        if row is None:
            self.misses += 1
            return None
        self.hits += 1
        return {
            "response": json.loads(row[0]),
            "prompt_tokens": row[1],
            "completion_tokens": row[2],
            "cache_hit": True,
        }

    def put(self, model: str, prompt: str, response: dict, prompt_tokens: int,
            completion_tokens: int, tools_schema=None):
        key = cache_key(model, prompt, tools_schema)
        self._conn.execute(
            "INSERT OR REPLACE INTO response_cache "
            "(key, model, response_json, prompt_tokens, completion_tokens) VALUES (?, ?, ?, ?, ?)",
            (key, model, json.dumps(response), prompt_tokens, completion_tokens),
        )
        self._conn.commit()

    def stats(self) -> dict:
        total = self.hits + self.misses
        return {
            "hits": self.hits,
            "misses": self.misses,
            "hit_rate": self.hits / total if total else 0.0,
        }

    def close(self):
        self._conn.close()
