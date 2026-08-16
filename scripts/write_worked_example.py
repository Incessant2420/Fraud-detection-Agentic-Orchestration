"""Picks one real, richly-evidenced case from a completed eval run and
writes it out as a full worked example for the README."""
import json
import sys

RUN_ID = sys.argv[1] if len(sys.argv) > 1 else "full-eval-001"


def main():
    rows = []
    with open(f"data/eval_runs/{RUN_ID}.jsonl") as f:
        for line in f:
            r = json.loads(line)
            if r.get("final_report") and len(r["final_report"]["findings"]) >= 2 \
                    and r.get("n_tool_calls", 0) >= 3:
                rows.append(r)

    if not rows:
        print("no sufficiently rich case found yet")
        return

    # prefer an ESCALATE_TO_HUMAN case where the escalation_reasons show the
    # deterministic gate actually did something -- the most illustrative case
    escalated = [r for r in rows if r.get("escalation_reasons")]
    case = escalated[0] if escalated else rows[0]
    fr = case["final_report"]

    lines = [
        f"# Worked Example: {fr['case_id']}\n",
        f"**Domain:** {fr['domain']}  **Disposition:** {fr['disposition']}  "
        f"**Confidence:** {fr['confidence']}\n",
    ]
    if case.get("escalation_reasons"):
        lines.append(f"**Deterministic escalation gate triggers:** {', '.join(case['escalation_reasons'])}\n")

    lines.append("\n## Investigative Timeline (tool calls, in order)\n")
    for ev in fr["evidence_ledger"]:
        lines.append(f"- **{ev['evidence_id']}** `{ev['tool_name']}({ev['arguments']})` "
                      f"-> _{ev['result_digest']}_")

    lines.append("\n## Findings\n")
    for f_ in fr["findings"]:
        lines.append(f"- **[{f_['strength']}]** {f_['claim']} "
                      f"(cites {', '.join(f_['evidence_ids'])}; supports_fraud={f_['supports_fraud']})")

    if fr["policy_citations"]:
        lines.append("\n## Policy Citations\n")
        for pc in fr["policy_citations"]:
            lines.append(f"- **{pc['policy_id']}**: {pc['excerpt']}")

    lines.append(f"\n## Reasoning Summary\n\n{fr['reasoning_summary']}\n")

    if fr["unresolved_questions"]:
        lines.append("\n## Unresolved Questions\n")
        for q in fr["unresolved_questions"]:
            lines.append(f"- {q}")

    out_path = "docs/worked_example.md"
    with open(out_path, "w") as f:
        f.write("\n".join(lines) + "\n")
    print(f"wrote {out_path} from case {fr['case_id']}")


if __name__ == "__main__":
    main()
