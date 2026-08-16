"""Applies hand-labels (produced by manually reviewing the hand-label pool)
and computes Cohen's kappa against the judge's labels on the same 50
findings."""
import json
import sys

from sentinel.eval.judge import cohens_kappa

RUN_ID = sys.argv[1] if len(sys.argv) > 1 else "full-eval-001"
POOL_PATH = f"data/eval_runs/{RUN_ID}_hand_label_pool.json"
HAND_LABELS_PATH = f"data/eval_runs/{RUN_ID}_hand_labels.json"


def main():
    with open(POOL_PATH) as f:
        pool = json.load(f)
    with open(HAND_LABELS_PATH) as f:
        hand_labels = json.load(f)  # list of {"case_id":..., "finding_index":..., "hand_label":...}

    hl_lookup = {(h["case_id"], h["finding_index"]): h["hand_label"] for h in hand_labels}

    judge_labels, human_labels = [], []
    for item in pool:
        key = (item["case_id"], item["finding_index"])
        if key not in hl_lookup:
            continue
        judge_labels.append(item["judge_label"])
        human_labels.append(hl_lookup[key])

    kappa = cohens_kappa(human_labels, judge_labels)
    agreement = sum(1 for a, b in zip(human_labels, judge_labels) if a == b) / len(human_labels)

    out = {
        "run_id": RUN_ID, "n_labeled": len(human_labels), "cohens_kappa": kappa,
        "raw_agreement": agreement,
        "judge_label_distribution": {lbl: judge_labels.count(lbl) for lbl in set(judge_labels)},
        "hand_label_distribution": {lbl: human_labels.count(lbl) for lbl in set(human_labels)},
    }
    out_path = f"data/eval_runs/{RUN_ID}_kappa.json"
    with open(out_path, "w") as f:
        json.dump(out, f, indent=2)
    print(json.dumps(out, indent=2))
    print(f"\nwrote {out_path}")


if __name__ == "__main__":
    main()
