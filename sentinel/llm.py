"""Thin Groq client wrapper: routes through the response cache first, tracks
tokens via TokenBudgetTracker, and never lets model names leak into call
sites -- callers pass a *node name* ("executor", "synthesizer", "critic",
"judge") and this module resolves it via config/models.yaml.
"""
import json
import os
from pathlib import Path

import yaml
from dotenv import load_dotenv
from groq import Groq

from sentinel.budget import TokenBudgetTracker, BudgetExceeded
from sentinel.cache import ResponseCache

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

_MODELS_CFG = yaml.safe_load(open(ROOT / "config" / "models.yaml"))
_client = None


def _get_client() -> Groq:
    global _client
    if _client is None:
        _client = Groq(api_key=os.environ["GROQ_API_KEY"])
    return _client


def model_for(node: str) -> str:
    return _MODELS_CFG[node]["model"]


class LLMRouter:
    """Bound to one run_id so budget/cache/logging are consistent across a case."""

    def __init__(self, run_id: str, cache: ResponseCache, budget: TokenBudgetTracker,
                 use_cache: bool = True):
        self.run_id = run_id
        self.cache = cache
        self.budget = budget
        self.use_cache = use_cache

    def call(self, node: str, prompt: str, case_id: str | None = None,
              response_format_json: bool = True) -> dict:
        cfg = _MODELS_CFG[node]
        model = cfg["model"]

        if self.use_cache:
            cached = self.cache.get(model, prompt)
            if cached is not None:
                self.budget.record(self.run_id, node, model, 0, 0, case_id=case_id)
                return {"content": cached["response"]["content"], "cached": True,
                        "prompt_tokens": 0, "completion_tokens": 0}

        self.budget.check_and_raise_if_exceeded(self.run_id, model=model)

        kwargs = dict(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=cfg.get("temperature", 0.2),
            max_tokens=cfg.get("max_tokens", 1024),
        )
        if response_format_json:
            kwargs["response_format"] = {"type": "json_object"}

        resp = _get_client().chat.completions.create(**kwargs)
        content = resp.choices[0].message.content
        prompt_tokens = resp.usage.prompt_tokens
        completion_tokens = resp.usage.completion_tokens

        self.budget.record(self.run_id, node, model, prompt_tokens, completion_tokens, case_id=case_id)
        if self.use_cache:
            self.cache.put(model, prompt, {"content": content}, prompt_tokens, completion_tokens)

        return {"content": content, "cached": False,
                "prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens}


def safe_json_loads(text: str) -> tuple[dict | None, bool, str | None]:
    """Returns (parsed, repair_was_applied, error). Tries strict json first,
    falls back to json_repair."""
    try:
        return json.loads(text), False, None
    except Exception:
        pass
    try:
        from json_repair import repair_json
        repaired = repair_json(text)
        return json.loads(repaired), True, None
    except Exception as e:
        return None, True, str(e)
