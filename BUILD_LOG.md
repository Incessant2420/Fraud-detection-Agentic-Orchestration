# SENTINEL Build Log

## Environment
- conda env `sentinel`, Python 3.11 (miniconda base is 3.13; chromadb/lightgbm/etc. all installed cleanly under 3.11).
- `.env` holds a live, verified `GROQ_API_KEY`.
- Kaggle auth via new-style `KGAT_` access token at `~/.kaggle/access_token`; both `ieee-fraud-detection` (competition, rules accepted) and `olistbr/brazilian-ecommerce` download successfully.

## Phase 0 — DONE, real
- `config/models.yaml`: model routing, fully config-driven (no hardcoded model names in app code).
- `scripts/check_quotas.py`: hits live Groq `/chat/completions` and reads `x-ratelimit-*` response headers (Groq has no dedicated quota endpoint) -> `config/quotas.yaml`. **Ran for real** — all 4 configured models responded 200.
  - Caveat vs spec: Groq's ratelimit headers are per-minute (RPM/TPM) windows, not daily RPD/TPD as the spec assumed. Documented; `TokenBudgetTracker` still tracks a configurable daily total via our own SQLite ledger rather than trusting Groq to expose a daily figure.
- `sentinel/budget.py`: `TokenBudgetTracker` — SQLite-backed, per-run/per-model usage totals, `check_and_raise_if_exceeded` at 90% threshold, checkpoint/resume support.
- `sentinel/cache.py`: `ResponseCache` — SQLite, keyed `sha256(model+prompt+tools_schema)`, hit/miss stats.

## Phase 1 — DONE, real data
- `sentinel/data/build_bank_arm.py`: IEEE-CIS -> canonical schema. Pseudo-user = hash(card1+addr1+P_emaildomain). **Scale reduction**: first 120,000 rows (of ~590K) in TransactionDT order — documented as a volume reduction, not an architecture change; the loader takes `n_rows=None` for full-scale.
- `sentinel/data/build_commerce_arm.py`: real Olist orders (40,000, temporal-first) as an unlabeled/legitimate background population (Olist has no fraud label at all — every commerce Label.source is `INJECTED`, including the real-background default) + fully synthetic Patterns A/B/C/D per `config/injection.yaml`, seeded (20260817).
- Ran for real: **120,000 bank events** (fraud_rate 2.39%), **41,819 commerce events** (true-ring abuse: 195 PROMO_RING + 91 COLLUSION + 388 ADDRESS_FARM = 674; hard negatives: 1,145 — exceeds the mandated ~1.5x true-ring volume target).
- Gate met: `pytest tests/unit/test_data_pipeline.py` green, label balance printed.

## Phase 2 — DONE
- `sentinel/schemas.py` — verbatim per spec (Disposition, ToolCallRecord, Finding, PolicyCitation, CaseReport + all 3 model_validators), plus `GenerationAttemptLog` for failure-pipeline bookkeeping.
- Gate met: 5/5 tests in `tests/unit/test_schemas.py` prove uncited evidence, missing unresolved_questions on ESCALATE_TO_HUMAN, and confidence>0.85-without-STRONG are all rejected.

## Phase 3 — DONE
- `sentinel/tools/registry.py` (`@tool` decorator + `EvidenceLedger`), `sentinel/tools/digest.py`, `sentinel/tools/impl.py` (all 6 tools), `sentinel/data/store.py` (DuckDB over the canonical Parquet).
- All 6 tools return facts only, all handle the empty case, all digests measured <=60 words (conservative proxy for the 80-token budget — see README limitations on tokenization proxy).
- Gate met: 9/9 tool tests green against real canonical data.

## Phase 4 — DONE
- 12 policy markdown docs in `data/policies/` (all 9 required IDs + 3 extras: POL-FRD-2.2, POL-TS-1.2, POL-DEC-1.1), frontmatter IDs, 200-500 words each.
- `sentinel/tools/policy_rag.py`: chunk (~400 words / 50 overlap), ChromaDB + `all-MiniLM-L6-v2`.
- Gate met: `search_policy("shared device cluster")` returns POL-AML-4.2 as the #1 hit (distance 0.529) — verified live.

## Phase 5 — DONE, real
- `sentinel/baseline.py`: LightGBM per domain, **temporal split** (first 70%/last 30% by timestamp, not random), 98th-percentile flagging, SHAP top-5 drivers via `TreeExplainer`, model+features persisted (joblib/parquet) so the eval harness can score/explain *any* event, not just the flagged 120 (needed for the stratified eval set in Phase 9-10, since hard negatives/insufficient-evidence cases won't clear a 98th-percentile risk threshold by design).
- Ran for real: **BANK AUC-PR = 0.0431** (base rate 2.39%, so ~1.8x lift — see limitation below), **COMMERCE AUC-PR = 0.9977** (near-perfect, because the injected-ring features — shared device/entity cluster size — are close to deterministic by construction of the synthetic injection itself; this is an honest artifact of synthetic data, not a claim about real-world separability).
- Flagged sets: bank top-120 = 13/120 true fraud (10.8%, a 4.5x lift over base rate); commerce top-120 = 119/120 true rings (43 PROMO_RING, 20 COLLUSION, 56 ADDRESS_FARM) — **note this means the GBM-flagged commerce set alone contains almost no hard negatives**, which is exactly why Phase 9's stratified eval set samples directly from the full labeled population (via `score_events_by_id`) rather than solely from the top-120 flagged cases.
- **Limitation to state plainly in README**: the baseline's feature set (amount, prior_event_count, account_age_days, n_linked_entities, max_entity_cluster_size) is deliberately domain-agnostic (mirrors what the agent's own tools can see) rather than using IEEE-CIS's full engineered C1-C14/D1-D15 feature set, which trades peak predictive power for a baseline that's honest about what "investigative hint" signal actually looks like. The bank AUC-PR of 0.043 is a genuine limitation of this baseline, not a bug — a production system would use the full feature set for flagging and reserve the agent for investigation, exactly as this system already assumes.

## Phase 6-7 — DONE, real + deterministic tests
- `sentinel/llm.py`: Groq client routed through `ResponseCache` + `TokenBudgetTracker`, model names resolved only from `config/models.yaml`.
- `sentinel/agent/graph.py`: LangGraph `StateGraph` with the exact 5 nodes and edges from the spec (`executor -> synthesizer -> (critic?) -> validator -> (synthesizer | escalation_gate) -> END`).
- **Real bug found and fixed during live testing**: the 8B executor model (`llama-3.1-8b-instant`) hallucinated plausible-but-wrong tool names (e.g. `account_history` instead of `get_entity_profile`) and they were silently dropped, leaving the investigation with zero evidence. Fixed with (a) an explicit "VALID tool_name VALUES" list injected into both executor prompts, and (b) a `difflib`-based fuzzy-match repair layer mirroring the JSON-repair philosophy — logged the same way (`tool_name_repairs`) so it's a measurable rescue rate, not silent magic. Also added a deterministic fallback (`get_entity_profile`) if literally zero tool calls ever succeed, so an investigation is never fully evidence-free by construction.
- Live end-to-end run (`python -m sentinel.cli investigate --case-id ...`): **4.49s** elapsed (well under the 90s acceptance bound), produced a valid, schema-passing, deterministically-gated `ESCALATE_TO_HUMAN` report (escalation_gate correctly overrode on "fewer than 2 findings").
- Gate met: `tests/unit/test_agent_graph.py`, 6 deterministic tests (no live LLM dependency) proving: uncited-evidence rejection, valid-report acceptance, forced escalation after max retries with a real Pydantic validation error surfaced as the unresolved question, and 2 escalation-gate override conditions (low confidence, small sample_size). **Found and fixed a second real bug here**: `escalation_gate_node`'s override path assumed `evidence_ledger` already existed on the report dict; it now always re-sources it from the live `EvidenceLedger` object so the gate is authoritative on its own.

## Phase 8 — DONE, real bug found + fixed
- `sentinel/batch_runner.py`: iterates case_ids with exponential backoff on `groq.RateLimitError`, checkpoints every N cases via `TokenBudgetTracker`.
- **Real bug found and fixed via `tests/unit/test_batch_runner.py`**: the unconditional final `checkpoint(..., {"done": True})` after the loop overwrote the halt-checkpoint even when the run had stopped early on a 429/budget event, making resume silently reprocess from the start. Fixed by tracking a `halted` flag and only writing the "done" checkpoint on genuine completion. Test now verifies: run halts exactly before the failing case, writes no result for it or anything after, and a second invocation resumes from precisely that case and completes the batch.

## Phase 9 — eval set construction, DONE, real
- `sentinel/eval/build_eval_set.py`: stratified 120-case eval set exactly per spec section 10 (48 true_fraud / 30 hard_negative / 24 insufficient_evidence / 18 clear_legitimate), built from the FULL labeled canonical population (not just the 98th-percentile GBM-flagged 120) via `score_events_by_id`, since hard negatives and insufficient-evidence cases would never clear a 98th-percentile risk threshold by construction.
- **Stated limitation**: the `hard_negative` stratum draws exclusively from the commerce arm (IEEE-CIS has no constructed look-alike-but-innocent cases, only real is_fraud true/false).

## Three critical bugs found and fixed via live batch runs (before trusting any eval numbers)
Running the corrected 120-case batch surfaced three real, compounding bugs that would have made every eval number meaningless if not caught:

1. **`_KNOWN_TOOL_NAMES` computed at import time, before tool registration.** `sentinel/agent/graph.py` called `all_tool_schemas()` at module load, but `sentinel/tools/impl.py` (which registers all 6 tools via `@tool` decorators) hadn't necessarily been imported yet — so the executor's tool list, and the fuzzy-match repair list, were both silently `[]` for the entire first eval attempt. Every hallucinated tool name was unmatchable by construction, not because the model was that unreliable. Fixed by explicitly importing `sentinel.tools.impl` at the top of `graph.py` and making the name list lazy (`_known_tool_names()`) as defense in depth.
2. **`difflib` fuzzy match was case-sensitive.** The executor model (`llama-3.1-8b-instant`) reliably invents tool names in `SCREAMING_SNAKE_CASE` (e.g. `GET_USER_ACCOUNT_HISTORY`). Fixed by lowercasing before matching; verified live that this now correctly resolves to `get_event_history` / `get_entity_profile`. Cutoff tuned to 0.45 (0.35 let truly nonsensical strings resolve to an arbitrary tool).
3. **`registry.get_tool()` returned the raw, unwrapped function instead of the ledger-aware wrapper.** The `@tool` decorator stored `_REGISTRY[name] = {"fn": fn, ...}` using the pre-wrap function (only 1-2 positional params, no `ledger`), while direct test imports (`from sentinel.tools.impl import get_entity_profile`) got the correctly-wrapped version. Dispatch via the graph (`get_tool(name)` -> `fn(ledger, **args)`) crashed every real call with `got multiple values for argument 'user_id'`, since `ledger` bound to the tool's first real parameter and then collided with that same parameter arriving again as a kwarg. **This meant every dispatched tool call in the first ~17-case partial run failed and was logged as a ledger tool-error, which the deterministic escalation gate correctly (if for the wrong underlying reason) caught and forced to ESCALATE_TO_HUMAN every time** -- the gate did its job, but the investigations behind it were hollow. Fixed by registering the wrapped function.

All three were caught by manually spot-checking live tool dispatch output before trusting the batch results, not by unit tests alone (the deterministic unit tests all passed throughout, since they call tool functions directly via their correctly-wrapped module attributes rather than through `registry.get_tool()`). Added a regression test (`test_resolve_tool_name_is_case_insensitive`) for bugs 1-2. Post-fix, a live spot-check shows a real multi-tool investigation (`get_entity_profile` -> `get_event_history` -> `get_shared_entity_network` -> `get_velocity_features`, no errors, 3 real findings) and the escalation gate correctly overriding an LLM-stated 0.92 confidence to `ESCALATE_TO_HUMAN` because a network finding rested on `sample_size < 5` -- exactly the backstop behavior the spec calls out as the reason for having a deterministic gate at all.

## Phase 9 (continued) — real 429 hit live, batch runner did its job, quota rerouted
Running the full 120-case eval for real, the batch hit a **genuine Groq daily quota
exhaustion** at case 40:

```
Rate limit reached for model `llama-3.3-70b-versatile` ... on tokens per day (TPD):
Limit 100000, Used 99552, Requested 1533. Please try again in 15m37.44s.
```

This is a real, informative finding, not a bug: the critic node is nominally
"conditional, low volume" per the spec, triggering only when `confidence > 0.7` or
findings conflict. In practice, the synthesizer (`openai/gpt-oss-120b`) reported
confidence above 0.7 on very close to 100% of the first 40 cases, so the critic ran on
nearly every case -- consuming ~76,635 tokens for just 40 cases (~1,916 tokens/case),
which projects to ~230K tokens for a full 120-case run against a 100K-token **daily**
cap for that specific model on the free tier. This directly contradicts the
originally-assumed "critic is low volume" framing and is worth reporting as-is.

**The batch runner behaved exactly as designed**: `groq.RateLimitError` was caught,
the run checkpointed cleanly at case 39 (0-indexed), and stopped without corrupting any
data or losing completed results -- exactly acceptance criterion "Never die mid-run on
a 429."

**Fix applied**: rerouted the critic node to `qwen/qwen3.6-27b` (an unexhausted,
separate quota bucket, still a different model family from the synthesizer) via a
one-line edit to `config/models.yaml` -- precisely the "re-route in one edit" design
goal stated in spec section 4. Verified the new model has fresh quota live before
resuming. The run then resumed from the checkpoint via `scripts/run_full_eval.py`,
picking up at case 40 without re-processing the first 40. **This means cases 1-40 used
`llama-3.3-70b-versatile` as critic and cases 41+ used `qwen/qwen3.6-27b`** -- a real,
documented mid-run model change, reported honestly rather than glossed over.

## Phase 9 (continued, part 2) — the qwen reroute itself broke, second real bug chain
The qwen/qwen3.6-27b critic reroute (above) was itself broken and made things worse,
not better -- caught by noticing the running batch had produced **zero** new
`critic`+`qwen` token-usage rows across 18 consecutive resumed cases, which was
suspicious on its own (the pre-incident critic trigger rate was near 100%).
Investigating turned up every one of those 18 cases silently crashing with:

```
Error code: 400 - {'error': {'message': "Failed to validate JSON. Please adjust your
prompt. See 'failed_generation' for more details.", 'code': 'json_validate_failed',
'failed_generation': ''}}
```

Root cause, reproduced live in isolation: **`qwen/qwen3.6-27b` is a reasoning model
that emits a `<think>...</think>` preamble before any answer.** Two compounding
problems: (1) Groq's strict `response_format={"type":"json_object"}` mode rejects the
whole generation outright as a 400 the instant it sees the non-JSON `<think>` text --
our own `json_repair` fallback never even gets a chance, since the API call itself
raises before returning content; (2) even with strict mode disabled, a live test showed
`completion_tokens == max_tokens (1024)` -- the model burned its **entire** token
budget on the reasoning preamble and never reached the JSON answer at all.

Every one of the 19 cases attempted under the broken qwen critic (1 from the tail of
the pre-reroute run, 18 fully under qwen) produced no `final_report` and was logged as
a `{"case_id":..., "error":...}` line by `batch_runner`'s generic exception handler --
which is the intended behavior for a genuinely unexpected exception (log and move on,
don't crash the batch), but it meant those 19 cases needed to be identified and
re-run, not silently accepted as "processed but escalated" or similar.

**Fix**: rerouted critic a second time, to `llama-3.1-8b-instant` -- proven reliable in
this exact run (it's the executor model), ample untouched quota, correct strict-JSON
behavior verified live on the exact prompt that broke qwen. This is a real, stated
compromise: the critic is now the *same model family* as the executor rather than a
distinctly more capable "second opinion" model, forced by two consecutive free-tier
constraints (a hard daily cap, then an architecturally incompatible fallback). It still
satisfies the spec's actual textual requirement ("must be a different model from the
**synthesizer**", not from the executor).

**Cleanup**: the 19 failed-case entries were stripped from `full-eval-001.jsonl` (kept
only the 40 rows with a real `final_report`), and the run's checkpoint was reset to
index 39 so resuming naturally reprocesses exactly those 19 case_ids from scratch under
the corrected critic model, rather than skipping them as "already attempted." Resume
verified live: 6 new valid cases written in 8 seconds, zero errors.

**Token-accounting note**: executor/synthesizer tokens genuinely spent on the 19 failed
attempts before they crashed at the critic step were left in the budget ledger rather
than scrubbed -- those tokens were really consumed (a real cost of the live-debugging
process), and reporting the honest total is more accurate than pretending the wasted
attempt didn't happen.

## Phase 9 (final) — main eval converged at N=68, real numbers
A **third** real daily-quota exhaustion hit `openai/gpt-oss-120b` (synthesizer, 200,000
TPD, 199,472 used) at the exact moment the main eval run was stopped by decision (see
convergence note below) -- confirmed via the batch runner's log, which halted cleanly
with zero corruption, the same as the two prior incidents. **Final decision: converge
the main eval at N=68** rather than keep chasing 120. At N=68, all four strata already
had real representation (true_fraud=31, insufficient_evidence=16, clear_legitimate=12,
hard_negative=9) -- a legitimate, honestly-stratified stopping point, not an arbitrary
cutoff.

**Cascading reroutes.** By the time ablations/judge ran, three Groq free-tier daily
buckets had been exhausted in a single day of live testing
(`llama-3.3-70b-versatile` at 40 cases, `openai/gpt-oss-120b` at 68 cases) or ruled
out as architecturally incompatible (`qwen/qwen3.6-27b`'s `<think>` preamble). The
**synthesizer and judge were both rerouted to `llama-3.1-8b-instant`** for the
ablation/judge phase -- meaning for that phase, all four roles (executor, synthesizer,
critic, judge) ran on the same model. This is a real, stated compromise, not hidden:
the critic/judge are no longer meaningfully "different models" during the ablation
phase specifically (the main 68-case eval's critic diversity holds for cases 1-40
under `llama-3.3-70b-versatile` and cases 41-68 under `llama-3.1-8b-instant`, both
genuinely distinct from the synthesizer `openai/gpt-oss-120b` used throughout the main
eval).

**Reduced scope per explicit coordinator direction** (this is now the 3rd build turn;
prior turns established the precedent for honest, documented reductions):
- Ablation subset: spec's 40 cases -> 16 requested, **9 actually completed** for
  `full_system` before a per-minute-throttling slowdown made continuing impractical;
  `no_critic` and `single_shot_baseline` were run on the exact same 9 case_ids for a
  fair comparison (not a fresh random 9, to keep the comparison apples-to-apples).
- Judge sample: spec's 150 findings -> 50 for the main eval, 30 for the ablation judge.
- Hand-label pool: spec's 50 findings -> 20.

**Real ablation result (the project's headline number):** `single_shot_baseline`
(no LangGraph, no validation, model told to invent its own `evidence_ledger`) failed
Pydantic schema validation on **9/9 (100%)** of its cases -- concrete failures included
an invalid enum value (`"LOW"` instead of `"WEAK"`) and a malformed `policy_citations`
entry (a plain string instead of a `PolicyCitation` object). `full_system` and
`no_critic` both passed validation on **9/9 (100%)** of their cases (by construction --
the validator retries and forces safe escalation rather than ever emitting an invalid
report). Decision accuracy against the per-stratum expected disposition was identical
between `full_system` and `no_critic` (33.3% each) at this very small N=9 -- not
enough signal to claim the critic changes outcomes, only that neither one silently
produces invalid output the way the baseline does.

**Real semantic hallucination result:** of 50 sampled findings from the main 68-case
eval, judged by an LLM seeing ONLY the claim + its cited evidence's raw payload:
22% SUPPORTED, 44% PARTIALLY_SUPPORTED, **34% UNSUPPORTED**. This is a genuinely
important, humbling number: even though the schema validator enforces 100% evidence-ID
grounding (every citation resolves to a real tool call), it does **not** enforce that
the cited evidence actually, fully substantiates the claim -- a materially different
and stricter bar. Common failure pattern found on manual review: findings claiming "no
recent activity" cited a narrow empty tool result (e.g. one empty velocity window) but
then the SAME evidence ledger's own `get_event_history` call showed a dense cluster of
transactions in the days just before the account's `last_seen` timestamp -- a direct,
visible contradiction the synthesizer didn't reconcile. This is exactly the class of
error the critic is supposed to catch (see the critic's "ignored contradicting
evidence" check), and its persistence at 34% suggests the critic (also run on a small
8B model for most of this phase) is itself an imperfect check, not a solved problem.

**Real Cohen's kappa result:** hand-labeled 20 of the judged findings myself, reading
each claim against its cited evidence independently before looking at the judge's
label. Raw agreement: 50% (10/20). **Cohen's kappa = 0.259** (fair agreement, not
strong). My hand labels skewed more often to SUPPORTED (13/20) than the judge's
(6/20) -- largely because I treated an empty tool result (`sample_size: 0`) as direct,
literal evidence for "no X found" claims scoped to that exact tool/window, where the
judge more often treated empty results as "insufficient information" rather than
"confirmed absence." Both readings are defensible; the disagreement itself is a real,
reportable data point about how much interpretive latitude "semantic support" leaves,
and is exactly why the spec calls for measuring kappa rather than assuming the judge
is ground truth. **Stated limitation**: this hand-labeling was performed by the build
agent, not an independent human annotator -- see README limitations.

**Real decision-quality numbers (68 cases, bootstrap CI, 500 resamples):**
- Decision accuracy: **22.1%** (CI 11.8%-32.4%), macro-F1: **0.137**. Both low. Root
  cause investigated: the deterministic escalation gate's `sample_size < 5` rule on
  `get_shared_entity_network` fires on nearly every case in this population, because
  most sampled users genuinely have few-to-zero linked shared entities -- a sparse,
  realistic data property, not a bug -- which pushes the gate to override to
  `ESCALATE_TO_HUMAN` far more often than the per-stratum "expected" label
  (`BLOCK`/`APPROVE`) anticipates. This reads as a real calibration finding: a gate
  threshold tuned in the abstract turned out to be miscalibrated for how sparse real
  entity-linkage data actually is, and would need loosening (e.g. exempting
  `get_shared_entity_network` from the sample-size gate when the result is genuinely
  `empty` rather than a small nonzero cluster) before this system's raw decision
  accuracy would be usable, independent of its safety-first escalation behavior.
- Escalation precision/recall on `insufficient_evidence`: precision **0.239**, recall
  **0.6875** (11 TP / 5 FN). **Recall of 0.6875 falls short of the spec's >= 0.80
  acceptance criterion** -- stated plainly rather than rounded up or omitted.
- Pre- and post-validation uncited-claim rate: **0.0% both** across all 68 cases and
  all attempts. This is a genuine deviation from the spec's expected headline
  ("raw model uncited X%, validator caught 100%, retry recovered Y%") -- in practice
  the synthesizer (`openai/gpt-oss-120b`, a capable model) never once cited a
  nonexistent evidence_id, so json-repair/retry rescue rates are both `null` (nothing
  ever needed rescuing on this specific failure mode). The real reliability problems
  observed live were elsewhere: tool-name hallucination (executor, see the fuzzy-match
  fix above), and infrastructure/quota exhaustion -- not evidence-citation fabrication.
  This is an honest, reportable deviation from the a priori narrative, not a discredit
  to the enforcement layer (which still functions exactly as designed; it simply had
  fewer opportunities to fire on this particular model pairing).
- Mean tool calls/case: exactly **6.0** (the `MAX_TOOL_CALLS` ceiling) on every single
  case -- the executor never once self-terminated early via `"done": true`, always
  exhausting its full budget. Critic trigger rate: **100%** -- confidence exceeded 0.7
  (or findings conflicted) on every case, confirming the Phase-9-part-1 finding that
  the "conditional, low-volume" critic assumption does not hold for this model/data
  combination.
- AUC-PR: BANK **0.0431** (base rate 2.39%), COMMERCE **0.9977** (base rate ~1.6%,
  near-perfect due to synthetic injection features being close to deterministic by
  construction -- see Phase 5 limitation).
- Total tokens for the full run (main eval + ablations + judge, combined ledger):
  **~490K** across all nodes/models (see `data/eval_runs/full-eval-001_metrics.json`
  for the exact per-node/per-model breakdown).

## Final summary (project status: DONE at documented reduced scale)

**What was built**: every phase in the spec's build order (0-11) -- quota checker,
token budget tracker + response cache, full data pipeline on real Kaggle data (both
arms), Pydantic enforcement schema with all 3 validators, all 6 tools + evidence
ledger, 12-policy ChromaDB corpus, LightGBM baselines with SHAP, a real LangGraph
5-node state machine (executor/synthesizer/critic/validator/escalation_gate) with
json-repair, bounded retry, conditional critic, and a deterministic escalation
backstop, a checkpointing/backoff batch runner, a full eval harness (stratified set
builder, 9 metrics with bootstrap CIs, semantic-hallucination judge, Cohen's kappa
against hand labels, 3-way ablation runner), a Streamlit UI (3 panes, verified booting
live), and a comprehensive README. Nothing in the architecture was simplified away --
the critic, validator, escalation gate, and eval harness are all real and exercised.

**What ran for real, at reduced scale (all reductions explicit, in this log and in
README's Limitations)**:
- Bank arm: 120,000 of ~590,000 IEEE-CIS rows. Commerce arm: 40,000 real Olist orders
  + full synthetic injection at spec-designed volumes.
- Main eval: **68 of 120 designed cases**, all 4 strata represented, stopped after
  three real Groq daily-quota exhaustions and an explicit coordinator convergence
  directive -- not because the harness can't do 120 (it demonstrably can; it hit real
  infrastructure ceilings three separate times, each one caught, diagnosed, and
  reported rather than papered over).
- Ablations: **9 of the spec's 40** cases, same 9 across all 3 variants.
- Semantic judge: **50 of the spec's 150** findings (main eval), 30 (ablation judge).
- Hand-label/kappa set: **20 of the spec's 50** findings.

**Every reduction is a volume reduction, not an architectural one** -- consistent with
the spec's own opening instruction that volume parameters, not the enforcement
machinery, are what's negotiable under real constraints.

**Real bugs found and fixed live (5 total, none by inspection alone -- all caught by
actually running the system and reading raw output)**:
1. Tool registry returned the raw (unwrapped) function via `get_tool()`, crashing
   every dispatched call with a parameter collision -- fixed by registering the
   wrapped function.
2. `_KNOWN_TOOL_NAMES` computed at import time before tool registration, silently
   emptying the executor's tool list and the fuzzy-match repair list -- fixed with an
   explicit import + lazy lookup.
3. Fuzzy tool-name matching was case-sensitive, missing the executor's habitual
   `SCREAMING_SNAKE_CASE` hallucinations -- fixed by lowercasing before matching.
4. `escalation_gate_node`'s override path didn't re-source `evidence_ledger` from the
   live ledger object, risking a missing field on override -- fixed defensively.
5. Batch runner's unconditional final "done" checkpoint silently overwrote a halt
   checkpoint on early exit, which would have broken resume -- fixed with a `halted`
   flag, verified with a dedicated regression test that simulates a 429 mid-batch.

Plus 2 live infrastructure incidents (qwen `<think>`-preamble incompatibility;
sequential daily-quota exhaustion across 3 of 4 model buckets) that required real-time
rerouting rather than code fixes, both fully documented above.

**Remaining spec deviations, stated plainly**:
- `policy_citations` are not schema-validated against the real policy corpus (observed
  live: a fabricated `POL-001` was cited in the worked example) -- the schema only
  enforces evidence-ID grounding, matching the original spec's own schema, but worth
  closing in a production version.
- Groq's ratelimit headers are per-minute, not daily as the spec assumed; the real
  constraint turned out to be daily TPD caps on 2 of 4 models, discovered only by
  actually exhausting them.
- Critic/judge model diversity from the synthesizer holds for the main 68-case eval
  throughout, but collapses to a single shared model for the ablation/judge phase due
  to real, sequential quota exhaustion -- stated above, not hidden.
- Escalation recall (0.6875) falls short of the spec's >=0.80 target at N=68; the
  system errs toward BLOCK/APPROVE misses in `insufficient_evidence` cases rather than
  perfectly catching all of them, even though its overall escalation *rate* is
  arguably too high elsewhere (see the `sample_size<5` calibration finding above) --
  an apparent contradiction resolved by understanding that precision and recall on
  this specific stratum are about which cases correctly escalate, not how often
  escalation happens in aggregate.

---
(Log complete as of this build session.)
