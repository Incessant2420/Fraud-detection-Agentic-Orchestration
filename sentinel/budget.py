"""TokenBudgetTracker — logs tokens per call per model, halts cleanly at
90% of the configured daily quota, and checkpoints progress so a run can
resume instead of dying mid-batch.
"""
import json
import sqlite3
from pathlib import Path
from dataclasses import dataclass, field


class BudgetExceeded(Exception):
    """Raised when a call would push a model over its halt threshold."""


@dataclass
class TokenBudgetTracker:
    db_path: str
    daily_cap_total: int = 500_000
    halt_at_fraction: float = 0.90
    per_model_caps: dict = field(default_factory=dict)  # model -> daily TPD cap

    def __post_init__(self):
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.db_path)
        self._conn.execute(
            """CREATE TABLE IF NOT EXISTS token_usage (
                   id INTEGER PRIMARY KEY AUTOINCREMENT,
                   run_id TEXT NOT NULL,
                   case_id TEXT,
                   node TEXT NOT NULL,
                   model TEXT NOT NULL,
                   prompt_tokens INTEGER NOT NULL,
                   completion_tokens INTEGER NOT NULL,
                   total_tokens INTEGER NOT NULL,
                   ts TEXT NOT NULL DEFAULT (datetime('now'))
               )"""
        )
        self._conn.execute(
            """CREATE TABLE IF NOT EXISTS checkpoints (
                   run_id TEXT PRIMARY KEY,
                   last_case_index INTEGER NOT NULL,
                   state_json TEXT NOT NULL,
                   updated_at TEXT NOT NULL DEFAULT (datetime('now'))
               )"""
        )
        self._conn.commit()

    def record(self, run_id: str, node: str, model: str, prompt_tokens: int,
               completion_tokens: int, case_id: str | None = None) -> int:
        total = prompt_tokens + completion_tokens
        self._conn.execute(
            "INSERT INTO token_usage (run_id, case_id, node, model, prompt_tokens, "
            "completion_tokens, total_tokens) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (run_id, case_id, node, model, prompt_tokens, completion_tokens, total),
        )
        self._conn.commit()
        return total

    def total_used(self, run_id: str | None = None, model: str | None = None) -> int:
        q = "SELECT COALESCE(SUM(total_tokens), 0) FROM token_usage WHERE 1=1"
        params = []
        if run_id is not None:
            q += " AND run_id = ?"
            params.append(run_id)
        if model is not None:
            q += " AND model = ?"
            params.append(model)
        return self._conn.execute(q, params).fetchone()[0]

    def check_and_raise_if_exceeded(self, run_id: str, model: str | None = None):
        cap = self.per_model_caps.get(model, self.daily_cap_total) if model else self.daily_cap_total
        used = self.total_used(run_id=run_id, model=model)
        if used >= cap * self.halt_at_fraction:
            raise BudgetExceeded(
                f"model={model or 'ALL'} used {used}/{cap} tokens "
                f"(>= {self.halt_at_fraction:.0%} threshold) for run={run_id}"
            )

    def checkpoint(self, run_id: str, last_case_index: int, state: dict):
        self._conn.execute(
            "INSERT INTO checkpoints (run_id, last_case_index, state_json) VALUES (?, ?, ?) "
            "ON CONFLICT(run_id) DO UPDATE SET last_case_index=excluded.last_case_index, "
            "state_json=excluded.state_json, updated_at=datetime('now')",
            (run_id, last_case_index, json.dumps(state)),
        )
        self._conn.commit()

    def load_checkpoint(self, run_id: str) -> tuple[int, dict] | None:
        row = self._conn.execute(
            "SELECT last_case_index, state_json FROM checkpoints WHERE run_id = ?",
            (run_id,),
        ).fetchone()
        if row is None:
            return None
        return row[0], json.loads(row[1])

    def report_by_node_and_model(self, run_id: str) -> list[dict]:
        rows = self._conn.execute(
            "SELECT node, model, COUNT(DISTINCT case_id), SUM(prompt_tokens), "
            "SUM(completion_tokens), SUM(total_tokens) FROM token_usage "
            "WHERE run_id = ? GROUP BY node, model ORDER BY node, model",
            (run_id,),
        ).fetchall()
        return [
            {
                "node": r[0], "model": r[1], "cases": r[2],
                "prompt_tokens": r[3], "completion_tokens": r[4], "total_tokens": r[5],
            }
            for r in rows
        ]

    def close(self):
        self._conn.close()
