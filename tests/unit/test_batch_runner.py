"""Batch runner must survive a 429 (checkpoint + stop cleanly) and resume
from where it left off on the next invocation -- never re-processing
already-completed cases and never crashing the whole batch."""
import json

import httpx
import groq
import pytest

import sentinel.batch_runner as batch_runner


def _rate_limit_error():
    resp = httpx.Response(429, request=httpx.Request("POST", "https://api.groq.com/x"))
    return groq.RateLimitError("rate limited", response=resp, body=None)


@pytest.fixture
def fake_case_ids(tmp_path, monkeypatch):
    ids = [f"CASE-FAKE-{i}" for i in range(6)]
    monkeypatch.setattr(batch_runner, "load_case_context",
                         lambda cid: {"case_id": cid, "domain": "COMMERCE", "user_id": "U-1"})
    monkeypatch.setattr(batch_runner, "RESULTS_DIR", tmp_path)
    return ids


def test_batch_survives_429_and_resumes(fake_case_ids, monkeypatch, tmp_path):
    ids = fake_case_ids
    call_count = {"n": 0}

    def fake_run_case(case_context, llm):
        call_count["n"] += 1
        if case_context["case_id"] == "CASE-FAKE-3":
            raise _rate_limit_error()
        return {"final_report": {"case_id": case_context["case_id"], "disposition": "APPROVE"},
                "generation_log": [], "escalation_reasons": []}

    monkeypatch.setattr(batch_runner, "run_case", fake_run_case)
    monkeypatch.setattr(batch_runner, "_call_with_backoff",
                         lambda fn, *a, **kw: fn(*a, **kw))  # skip real sleep/backoff in test

    budget_db = tmp_path / "budget.sqlite"
    cache_db = tmp_path / "cache.sqlite"
    monkeypatch.setattr(batch_runner, "TokenBudgetTracker",
                         lambda path: __import__("sentinel.budget", fromlist=["TokenBudgetTracker"])
                         .TokenBudgetTracker(str(budget_db)))
    monkeypatch.setattr(batch_runner, "ResponseCache",
                         lambda path: __import__("sentinel.cache", fromlist=["ResponseCache"])
                         .ResponseCache(str(cache_db)))

    run_id = "test-run-429"
    result = batch_runner.run_batch(run_id, ids, use_cache=False, checkpoint_every=2)

    results_path = tmp_path / f"{run_id}.jsonl"
    lines = [json.loads(l) for l in open(results_path)]
    completed_case_ids = [l["case_id"] for l in lines]
    assert "CASE-FAKE-0" in completed_case_ids
    assert "CASE-FAKE-2" in completed_case_ids
    assert "CASE-FAKE-3" not in completed_case_ids  # halted before processing this one succeeded
    assert "CASE-FAKE-4" not in completed_case_ids
    assert "CASE-FAKE-5" not in completed_case_ids

    # --- resume: rate-limit case now succeeds, run should pick up from checkpoint ---
    def fake_run_case_v2(case_context, llm):
        return {"final_report": {"case_id": case_context["case_id"], "disposition": "APPROVE"},
                "generation_log": [], "escalation_reasons": []}

    monkeypatch.setattr(batch_runner, "run_case", fake_run_case_v2)
    batch_runner.run_batch(run_id, ids, use_cache=False, checkpoint_every=2)

    lines2 = [json.loads(l) for l in open(results_path)]
    completed_case_ids_2 = [l["case_id"] for l in lines2]
    assert completed_case_ids_2 == ["CASE-FAKE-0", "CASE-FAKE-1", "CASE-FAKE-2",
                                     "CASE-FAKE-3", "CASE-FAKE-4", "CASE-FAKE-5"]
