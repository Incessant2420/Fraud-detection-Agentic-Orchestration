"""Streamlit UI: three panes -- case list, case detail (with clickable
evidence grounding), network view. Run with:
    streamlit run sentinel/ui/app.py
"""
import json
from pathlib import Path

import pandas as pd
import streamlit as st
from streamlit_agraph import agraph, Node, Edge, Config

st.set_page_config(page_title="SENTINEL", layout="wide")

RESULTS_CANDIDATES = list(Path("data/eval_runs").glob("full-eval-*.jsonl"))
EVAL_SET_PATH = "data/processed/eval_set.parquet"


@st.cache_data
def load_data():
    eval_df = pd.read_parquet(EVAL_SET_PATH) if Path(EVAL_SET_PATH).exists() else pd.DataFrame()
    results = []
    if RESULTS_CANDIDATES:
        with open(sorted(RESULTS_CANDIDATES)[-1]) as f:
            for line in f:
                results.append(json.loads(line))
    results_by_case = {r["case_id"]: r for r in results}
    return eval_df, results_by_case


def render_case_list(eval_df: pd.DataFrame, results_by_case: dict):
    st.subheader("Case List")
    show_gt = st.checkbox("Show ground truth", value=False)
    rows = []
    for _, row in eval_df.iterrows():
        r = results_by_case.get(row["case_id"])
        fr = (r or {}).get("final_report")
        rows.append({
            "case_id": row["case_id"], "domain": row["domain"], "stratum": row["stratum"],
            "baseline_risk_score": round(row["risk_score"], 3),
            "disposition": fr["disposition"] if fr else "(not run)",
            "confidence": round(fr["confidence"], 2) if fr else None,
            **({"ground_truth_is_fraud": row["ground_truth_is_fraud"],
                "abuse_type": row["abuse_type"]} if show_gt else {}),
        })
    df = pd.DataFrame(rows)
    selected = st.dataframe(df, use_container_width=True, height=400,
                             on_select="rerun", selection_mode="single-row")
    if selected and selected["selection"]["rows"]:
        return df.iloc[selected["selection"]["rows"][0]]["case_id"]
    return None


def render_case_detail(case_id: str, eval_df: pd.DataFrame, results_by_case: dict):
    st.subheader(f"Case Detail: {case_id}")
    r = results_by_case.get(case_id)
    if r is None or r.get("final_report") is None:
        st.warning("No agent result available for this case.")
        return
    fr = r["final_report"]

    col1, col2 = st.columns([2, 1])
    with col1:
        st.markdown(f"**Disposition:** `{fr['disposition']}`  **Confidence:** {fr['confidence']:.2f}")
        st.markdown(f"**Reasoning:** {fr['reasoning_summary']}")

        st.markdown("### Investigative Timeline")
        for i, ev in enumerate(fr["evidence_ledger"]):
            with st.expander(f"{ev['evidence_id']} -- {ev['tool_name']}({ev['arguments']})"):
                st.code(ev["result_digest"], language=None)
                st.json(ev["raw_result"])

        st.markdown("### Findings (click to see cited evidence highlighted above)")
        for i, finding in enumerate(fr["findings"]):
            key = f"finding-{case_id}-{i}"
            if st.button(f"[{finding['strength']}] {finding['claim'][:80]}", key=key):
                st.session_state["highlighted_evidence"] = finding["evidence_ids"]
            if st.session_state.get("highlighted_evidence") and \
                    set(finding["evidence_ids"]) & set(st.session_state["highlighted_evidence"]):
                st.success(f"Cites: {', '.join(finding['evidence_ids'])} -- supports_fraud={finding['supports_fraud']}")

        if fr["policy_citations"]:
            st.markdown("### Policy Citations")
            for pc in fr["policy_citations"]:
                st.markdown(f"- **{pc['policy_id']}**: {pc['excerpt']} _(relevance: {pc['relevance']})_")

        if fr["unresolved_questions"]:
            st.markdown("### Unresolved Questions")
            for q in fr["unresolved_questions"]:
                st.markdown(f"- {q}")

    with col2:
        st.markdown("### Baseline Risk Context")
        row = eval_df[eval_df["case_id"] == case_id].iloc[0]
        st.metric("Baseline risk score", f"{row['risk_score']:.4f}")
        st.markdown("**Top SHAP drivers:**")
        drivers = json.loads(row["shap_drivers"]) if isinstance(row["shap_drivers"], str) else row["shap_drivers"]
        st.table(pd.DataFrame(drivers))


def render_network_view(case_id: str, results_by_case: dict, eval_df: pd.DataFrame):
    st.subheader("Entity Network")
    r = results_by_case.get(case_id)
    if r is None or r.get("final_report") is None:
        st.info("No network data for this case.")
        return
    fr = r["final_report"]
    row = eval_df[eval_df["case_id"] == case_id].iloc[0]
    gt_fraud = bool(row["ground_truth_is_fraud"])

    nodes, edges = [], []
    seen = set()
    for ev in fr["evidence_ledger"]:
        if ev["tool_name"] != "get_shared_entity_network":
            continue
        for n in ev["raw_result"].get("nodes", []):
            if n["id"] not in seen:
                color = "#e74c3c" if gt_fraud and n["kind"] == "USER" else "#3498db"
                nodes.append(Node(id=n["id"], label=n["id"][:12], color=color, size=15))
                seen.add(n["id"])
        for e in ev["raw_result"].get("edges", []):
            edges.append(Edge(source=e["source"], target=e["target"]))

    if not nodes:
        st.info("No shared-entity-network tool call was made for this case.")
        return
    config = Config(width=700, height=400, directed=False, physics=True)
    agraph(nodes=nodes, edges=edges, config=config)


def main():
    st.title("SENTINEL -- Investigation Copilot")
    eval_df, results_by_case = load_data()
    if eval_df.empty:
        st.error("No eval_set.parquet found. Run `python -m sentinel.eval.build_eval_set` first.")
        return

    selected_case = render_case_list(eval_df, results_by_case)
    if "current_case" not in st.session_state:
        st.session_state["current_case"] = eval_df["case_id"].iloc[0]
    if selected_case:
        st.session_state["current_case"] = selected_case
        st.session_state["highlighted_evidence"] = None

    tab1, tab2 = st.tabs(["Case Detail", "Network View"])
    with tab1:
        render_case_detail(st.session_state["current_case"], eval_df, results_by_case)
    with tab2:
        render_network_view(st.session_state["current_case"], results_by_case, eval_df)


if __name__ == "__main__":
    main()
