"""@tool decorator: registers a function, generates its JSON schema from the
signature, times execution, writes a ToolCallRecord into the case's
EvidenceLedger, and returns (evidence_id, digest).

Tools return facts, never judgements — no tool ever emits the word
"suspicious". The agent reasons over facts; this separation is what keeps
the reasoning trace meaningful and auditable.
"""
import inspect
import time
from datetime import datetime, timezone
from typing import Callable, get_type_hints

from sentinel.schemas import ToolCallRecord

_REGISTRY: dict[str, dict] = {}


def _python_type_to_json_type(t) -> str:
    mapping = {
        str: "string", int: "integer", float: "number",
        bool: "boolean", list: "array", dict: "object",
    }
    return mapping.get(t, "string")


def _build_json_schema(fn: Callable) -> dict:
    sig = inspect.signature(fn)
    hints = get_type_hints(fn)
    properties = {}
    required = []
    for name, param in sig.parameters.items():
        if name == "ledger":
            continue
        json_type = _python_type_to_json_type(hints.get(name, str))
        properties[name] = {"type": json_type}
        if param.default is inspect.Parameter.empty:
            required.append(name)
    return {
        "name": fn.__name__,
        "description": (fn.__doc__ or "").strip(),
        "parameters": {"type": "object", "properties": properties, "required": required},
    }


class EvidenceLedger:
    """Per-case store of ToolCallRecords. The LLM only ever sees
    result_digest; raw_result is retained here for the judge and UI."""

    def __init__(self):
        self._records: list[ToolCallRecord] = []
        self._counter = 0

    def next_evidence_id(self) -> str:
        self._counter += 1
        return f"EV-{self._counter:03d}"

    def add(self, record: ToolCallRecord):
        self._records.append(record)

    def all(self) -> list[ToolCallRecord]:
        return list(self._records)

    def digests_for_prompt(self) -> list[dict]:
        """What the executor/synthesizer LLM is allowed to see."""
        return [
            {"evidence_id": r.evidence_id, "tool": r.tool_name,
             "arguments": r.arguments, "digest": r.result_digest}
            for r in self._records
        ]

    def has_tool_error(self) -> bool:
        return any(r.raw_result.get("error") for r in self._records)


def tool(fn: Callable) -> Callable:
    schema = _build_json_schema(fn)

    def wrapped(ledger: EvidenceLedger, /, **kwargs):
        start = time.perf_counter()
        raw_result = fn(**kwargs)
        latency_ms = int((time.perf_counter() - start) * 1000)
        digest = raw_result.get("_digest") or ""
        payload = {k: v for k, v in raw_result.items() if k != "_digest"}
        evidence_id = ledger.next_evidence_id()
        record = ToolCallRecord(
            evidence_id=evidence_id,
            tool_name=fn.__name__,
            arguments=kwargs,
            result_digest=digest,
            raw_result=payload,
            latency_ms=latency_ms,
            called_at=datetime.now(timezone.utc).isoformat(),
        )
        ledger.add(record)
        return evidence_id, digest

    wrapped.tool_name = fn.__name__
    wrapped.json_schema = schema
    wrapped.raw_fn = fn
    # Register the WRAPPED function, not the raw one -- get_tool() is used
    # by the agent graph's dispatch path (as opposed to tests, which import
    # the module attribute directly), and a raw fn(ledger, **kwargs) call
    # binds `ledger` to the function's first real parameter and then
    # collides with that same parameter arriving again as a kwarg (a real
    # "got multiple values for argument" bug found via a live batch run,
    # only reachable once the tool-name resolution bugs above were fixed
    # and dispatch actually started calling real tools).
    _REGISTRY[fn.__name__] = {"fn": wrapped, "schema": schema}
    return wrapped


def all_tool_schemas() -> list[dict]:
    return [v["schema"] for v in _REGISTRY.values()]


def get_tool(name: str):
    return _REGISTRY[name]["fn"]
