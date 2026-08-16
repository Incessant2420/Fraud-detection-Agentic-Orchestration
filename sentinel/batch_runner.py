"""Batch runner: iterates a list of case_ids through the agent graph, with
exponential backoff on Groq 429s and checkpointing so a run survives a rate
limit or crash and resumes rather than dying mid-batch.
"""
import json
import time
from pathlib import Path

import groq

from sentinel.agent.graph import run_case
from sentinel.budget import TokenBudgetTracker, BudgetExceeded
from sentinel.cache import ResponseCache
from sentinel.cli import load_case_context
from sentinel.llm import LLMRouter

RESULTS_DIR = Path("data/eval_runs")
MAX_BACKOFF_RETRIES = 5


def _call_with_backoff(fn, *args, **kwargs):
    delay = 2.0
    for attempt in range(MAX_BACKOFF_RETRIES):
        try:
            return fn(*args, **kwargs)
        except groq.RateLimitError:
            if attempt == MAX_BACKOFF_RETRIES - 1:
                raise
            time.sleep(delay)
            delay *= 2
    raise RuntimeError("unreachable")


def run_batch(run_id: str, case_ids: list[str], use_cache: bool = True,
              checkpoint_every: int = 5, case_contexts: dict | None = None,
              run_case_fn=None) -> dict:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    cache = ResponseCache("data/response_cache.sqlite")
    budget = TokenBudgetTracker("data/token_budget.sqlite")
    llm = LLMRouter(run_id=run_id, cache=cache, budget=budget, use_cache=use_cache)

    results_path = RESULTS_DIR / f"{run_id}.jsonl"

    start_index = 0
    ckpt = budget.load_checkpoint(run_id)
    if ckpt is not None:
        start_index = ckpt[0] + 1
        print(f"resuming run {run_id} from case index {start_index}/{len(case_ids)}")

    halted = False
    mode = "a" if start_index > 0 else "w"
    with open(results_path, mode) as f:
        for i in range(start_index, len(case_ids)):
            case_id = case_ids[i]
            try:
                case_context = case_contexts[case_id] if case_contexts else load_case_context(case_id)
                fn = run_case_fn or run_case
                result = _call_with_backoff(fn, case_context, llm)
                f.write(json.dumps({"case_id": case_id, **result}, default=str) + "\n")
                f.flush()
            except BudgetExceeded as e:
                print(f"halting cleanly at case {i}/{len(case_ids)}: {e}")
                budget.checkpoint(run_id, i - 1, {"halted_on_budget": True})
                halted = True
                break
            except groq.RateLimitError as e:
                print(f"rate limit exhausted after backoff at case {i}, checkpointing and stopping: {e}")
                budget.checkpoint(run_id, i - 1, {"halted_on_ratelimit": True})
                halted = True
                break
            except Exception as e:
                print(f"case {case_id} raised {type(e).__name__}: {e} -- recording as failure, continuing")
                f.write(json.dumps({"case_id": case_id, "error": str(e)}) + "\n")
                f.flush()

            if (i + 1) % checkpoint_every == 0:
                budget.checkpoint(run_id, i, {"completed_through": i})

    # Only mark the run "done" if it actually reached the end -- a halt
    # (budget/rate-limit) must leave its own checkpoint intact so the next
    # invocation resumes from the halt point, not from a false "done".
    if not halted:
        budget.checkpoint(run_id, len(case_ids) - 1, {"done": True})

    report = budget.report_by_node_and_model(run_id)
    total_tokens = budget.total_used(run_id=run_id)
    cache_stats = cache.stats()
    cache.close()
    budget.close()

    return {
        "run_id": run_id, "results_path": str(results_path),
        "n_cases_requested": len(case_ids), "token_report": report,
        "total_tokens": total_tokens, "cache_stats": cache_stats,
    }
