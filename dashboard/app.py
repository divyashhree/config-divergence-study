"""
Research Exploration Dashboard — Streamlit Application

Displays real pipeline outputs for research exploration.
Never hardcodes sample metrics. Uses actual CSV/JSON from pipeline runs.
"""
import json
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

# Ensure src is importable
sys.path.insert(0, str(Path(__file__).parent.parent))

# ─────────────────────────────────────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────────────────────────────────────

DATA_DIR = Path(__file__).parent.parent / "data" / "outputs"
AVAILABLE_RUNS = sorted(
    [d.name for d in DATA_DIR.iterdir() if d.is_dir()],
    reverse=True,
) if DATA_DIR.exists() else []

st.set_page_config(
    page_title="Config Divergence Study",
    page_icon="🔬",
    layout="wide",
    initial_sidebar_state="expanded",
)


# ─────────────────────────────────────────────────────────────────────────────
# Sidebar — Run Selection
# ─────────────────────────────────────────────────────────────────────────────

st.sidebar.title("🔬 Config Divergence Study")
st.sidebar.markdown("*Environment Configuration Divergence in Cloud-Native Projects*")
st.sidebar.divider()

if not AVAILABLE_RUNS:
    st.error("No pipeline runs found. Run `python run_pipeline.py` first.")
    st.stop()

selected_run = st.sidebar.selectbox(
    "Select Pipeline Run",
    AVAILABLE_RUNS,
    help="Choose a repository analysis to explore",
)

run_dir = DATA_DIR / selected_run


# ─────────────────────────────────────────────────────────────────────────────
# Load Data
# ─────────────────────────────────────────────────────────────────────────────

@st.cache_data
def load_data(run_path: str):
    """Load all data files from a pipeline run."""
    rp = Path(run_path)
    data = {}

    # Divergences
    div_path = rp / "divergences.csv"
    if div_path.exists():
        data["divergences"] = pd.read_csv(div_path)

    # Category summary
    cat_path = rp / "category_summary.csv"
    if cat_path.exists():
        data["categories"] = pd.read_csv(cat_path)

    # Env pair summary
    pair_path = rp / "env_pair_summary.csv"
    if pair_path.exists():
        data["env_pairs"] = pd.read_csv(pair_path)

    # Metrics
    metrics_path = rp / "snapshot_metrics.json"
    if metrics_path.exists():
        with open(metrics_path) as f:
            data["metrics"] = json.load(f)

    # Manifest
    manifest_path = rp / "run_manifest.json"
    if manifest_path.exists():
        with open(manifest_path) as f:
            data["manifest"] = json.load(f)

    # Figure
    fig_path = rp / "divergence_analysis.png"
    if fig_path.exists():
        data["figure_path"] = str(fig_path)

    return data


data = load_data(str(run_dir))

if "divergences" not in data:
    st.error(f"No divergence data found in {run_dir}")
    st.stop()

df = data["divergences"]
metrics = data.get("metrics", {})
manifest = data.get("manifest", {})


# ─────────────────────────────────────────────────────────────────────────────
# Tab Layout
# ─────────────────────────────────────────────────────────────────────────────

tab_overview, tab_explorer, tab_results, tab_quality = st.tabs([
    "📊 Overview", "🔍 Divergence Explorer", "📈 Research Results", "🛡️ Data Quality"
])


# ─────────────────────────────────────────────────────────────────────────────
# Tab 1: Overview
# ─────────────────────────────────────────────────────────────────────────────

with tab_overview:
    st.header("Study Overview")

    repo_id = manifest.get("repo_id", selected_run)
    st.subheader(f"Repository: `{repo_id}`")

    # Key metrics
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Total Divergences", metrics.get("raw_divergence_count", len(df)))
    col2.metric("Comparable Paths", metrics.get("total_comparable_paths", "—"))
    col3.metric(
        "Divergence Density",
        f"{metrics.get('raw_divergence_density', 0):.4f}",
    )
    col4.metric("Categories", len(metrics.get("category_counts", {})))

    col5, col6, col7, col8 = st.columns(4)
    col5.metric("High Confidence", metrics.get("high_confidence_count", 0))
    col6.metric("From Defaults", metrics.get("from_default_count", 0))
    col7.metric("Typically Env-Specific", metrics.get("typically_env_specific_count", 0))
    col8.metric(
        "Charts Analyzed",
        manifest.get("charts_with_envs", "—"),
    )

    st.divider()

    # Category breakdown
    st.subheader("Divergence by Category")
    if "categories" in data and not data["categories"].empty:
        cat_df = data["categories"]

        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        fig, ax = plt.subplots(figsize=(10, 5))
        colors = []
        for _, row in cat_df.iterrows():
            if row.get("typically_env_specific") is True:
                colors.append("#4CAF50")
            elif row.get("typically_env_specific") is False:
                colors.append("#FF9800")
            else:
                colors.append("#9E9E9E")

        ax.barh(cat_df["category"], cat_df["count"], color=colors)
        ax.set_xlabel("Number of Divergences")
        ax.set_title("Configuration Divergences by Category")
        ax.invert_yaxis()

        from matplotlib.patches import Patch
        legend_elements = [
            Patch(facecolor="#4CAF50", label="Typically env-specific (likely intentional)"),
            Patch(facecolor="#FF9800", label="Typically consistent (warrants attention)"),
            Patch(facecolor="#9E9E9E", label="Uncategorized"),
        ]
        ax.legend(handles=legend_elements, loc="lower right", fontsize=8)
        st.pyplot(fig)
        plt.close()

        st.caption(
            "**Note:** Category labels indicate the *type* of difference, "
            "not whether it is intentional or accidental. "
            "Green bars show categories where differences are commonly expected "
            "between environments (e.g., replica counts). "
            "Orange bars show categories where consistency is typically expected "
            "(e.g., health checks, security settings)."
        )
    else:
        st.info("No category summary available.")

    # Run metadata
    with st.expander("📋 Run Metadata"):
        if manifest:
            st.json(manifest)


# ─────────────────────────────────────────────────────────────────────────────
# Tab 2: Divergence Explorer
# ─────────────────────────────────────────────────────────────────────────────

with tab_explorer:
    st.header("Divergence Explorer")

    # Filters
    fcol1, fcol2, fcol3, fcol4 = st.columns(4)

    with fcol1:
        categories = ["All"] + sorted(df["category"].unique().tolist())
        sel_category = st.selectbox("Category", categories)

    with fcol2:
        diff_types = ["All"] + sorted(df["diff_type"].unique().tolist())
        sel_diff_type = st.selectbox("Diff Type", diff_types)

    with fcol3:
        confidences = ["All"] + sorted(df["confidence"].unique().tolist())
        sel_confidence = st.selectbox("Confidence", confidences)

    with fcol4:
        default_filter = st.selectbox(
            "Default Inheritance",
            ["All", "From Default", "Explicit Only"],
        )

    # Apply filters
    filtered = df.copy()
    if sel_category != "All":
        filtered = filtered[filtered["category"] == sel_category]
    if sel_diff_type != "All":
        filtered = filtered[filtered["diff_type"] == sel_diff_type]
    if sel_confidence != "All":
        filtered = filtered[filtered["confidence"] == sel_confidence]
    if default_filter == "From Default":
        filtered = filtered[filtered["is_from_default"] == True]
    elif default_filter == "Explicit Only":
        filtered = filtered[filtered["is_from_default"] == False]

    st.write(f"**Showing {len(filtered)} of {len(df)} divergences**")

    # Display columns
    display_cols = [
        "config_path", "category", "diff_type",
        "value_env_a", "value_env_b",
        "confidence", "is_from_default", "evidence_notes",
    ]
    available_cols = [c for c in display_cols if c in filtered.columns]

    st.dataframe(
        filtered[available_cols],
        use_container_width=True,
        height=500,
    )

    # Detail view
    if not filtered.empty:
        st.divider()
        st.subheader("Divergence Detail")
        idx = st.number_input(
            "Select row (0-indexed)",
            min_value=0,
            max_value=len(filtered) - 1,
            value=0,
        )
        row = filtered.iloc[idx]

        dcol1, dcol2 = st.columns(2)
        with dcol1:
            st.markdown("**Configuration Path:**")
            st.code(row.get("config_path", ""))
            st.markdown("**Category:**")
            st.write(row.get("category", ""))
            st.markdown("**Diff Type:**")
            st.write(row.get("diff_type", ""))
            st.markdown("**Confidence:**")
            st.write(row.get("confidence", ""))

        with dcol2:
            env_pair = row.get("env_pair", "").split("::")
            label_a = env_pair[0] if len(env_pair) > 0 else "env_a"
            label_b = env_pair[1] if len(env_pair) > 1 else "env_b"

            st.markdown(f"**Value in {label_a}:**")
            val_a = row.get("value_env_a", "")
            st.code(str(val_a) if pd.notna(val_a) else "(missing)")

            st.markdown(f"**Value in {label_b}:**")
            val_b = row.get("value_env_b", "")
            st.code(str(val_b) if pd.notna(val_b) else "(missing)")

            if row.get("is_from_default"):
                st.info("ℹ️ At least one value is inherited from chart defaults")

        st.markdown("**Evidence Notes:**")
        st.write(row.get("evidence_notes", ""))

        if row.get("source_file_a") or row.get("source_file_b"):
            st.markdown("**Source Files:**")
            st.write(f"- {row.get('source_file_a', '')}")
            st.write(f"- {row.get('source_file_b', '')}")


# ─────────────────────────────────────────────────────────────────────────────
# Tab 3: Research Results
# ─────────────────────────────────────────────────────────────────────────────

with tab_results:
    st.header("Research Results")

    st.subheader("RQ1 — What types of divergence occur?")

    if not df.empty:
        # Category distribution table
        cat_table = df.groupby("category").agg(
            Count=("divergence_id", "count"),
            High_Confidence=("confidence", lambda x: (x == "high").sum()),
            From_Default=("is_from_default", "sum"),
        ).sort_values("Count", ascending=False)
        cat_table["Proportion"] = (cat_table["Count"] / cat_table["Count"].sum()).round(4)
        st.dataframe(cat_table, use_container_width=True)

        # Diff type pie
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 5))

        type_counts = df["diff_type"].value_counts()
        ax1.pie(
            type_counts.values, labels=type_counts.index,
            autopct="%1.0f%%", startangle=90,
        )
        ax1.set_title("Difference Types")

        conf_counts = df["confidence"].value_counts()
        ax2.pie(
            conf_counts.values, labels=conf_counts.index,
            autopct="%1.0f%%", startangle=90,
            colors=["#4CAF50", "#FFC107", "#F44336"],
        )
        ax2.set_title("Confidence Levels")
        st.pyplot(fig)
        plt.close()

    st.divider()
    st.subheader("RQ2 — Classification Reliability")

    # Load real RQ2 results
    rq2_path = Path(__file__).parent.parent / "data" / "results" / "rq2_classification.json"
    if rq2_path.exists():
        with open(rq2_path) as f:
            rq2 = json.load(f)

        agreement = rq2.get("agreement_report", {})
        kappa = rq2.get("kappa")
        raw_agreement = rq2.get("raw_agreement")

        if kappa is not None:
            rcol1, rcol2, rcol3 = st.columns(3)
            rcol1.metric("Cohen's κ", f"{kappa:.3f}")
            rcol2.metric("Raw Agreement", f"{raw_agreement:.1%}" if raw_agreement else "—")
            rcol3.metric("Cases Labeled", agreement.get("n_cases", "—"))

            st.write(f"**Interpretation:** {rq2.get('interpretation', '—')}")

            # Confusion matrix
            confusion = agreement.get("confusion_matrix", {})
            if confusion:
                st.markdown("**Confusion Matrix (Reviewer A × Reviewer B):**")
                cm_df = pd.DataFrame(confusion).fillna(0).astype(int)
                st.dataframe(cm_df, use_container_width=True)

            # Disagreement details
            disagreements = agreement.get("disagreement_details", [])
            if disagreements:
                st.markdown(f"**Disagreements ({len(disagreements)}):**")
                for d in disagreements:
                    st.write(f"- `{d['divergence_id'][:12]}…`: "
                             f"A={d['label_a']}, B={d['label_b']}")

            # Label distributions
            for reviewer in ["reviewer_A", "reviewer_B"]:
                dist = rq2.get(f"label_distribution_{reviewer}", {})
                if dist:
                    st.write(f"**{reviewer} distribution:** {dist}")

            # Kappa paradox note
            if kappa == 0.0 and raw_agreement and raw_agreement >= 0.6:
                st.warning(
                    "⚠️ **Kappa Paradox:** High raw agreement but κ ≈ 0 occurs when "
                    "one label dominates. The expected agreement by chance equals the "
                    "observed agreement, so kappa cannot distinguish real agreement "
                    "from chance. This is a known limitation with highly skewed label "
                    "distributions and is itself a methodological finding."
                )

            # Bootstrap CI
            bootstrap = agreement.get("bootstrap_ci", {})
            if bootstrap:
                st.write(
                    f"**Bootstrap 95% CI:** [{bootstrap.get('ci_lower', '—')}, "
                    f"{bootstrap.get('ci_upper', '—')}]"
                )
        else:
            st.info("Agreement analysis completed but no kappa computed.")
    else:
        st.info(
            "Inter-rater agreement (Cohen's kappa) will be computed after "
            "two independent reviewers label a sample of divergences. "
            "See the annotation guide in `docs/annotation_guide.md`."
        )

    st.divider()
    st.subheader("RQ3 — Maintenance Association")

    rq3_path = Path(__file__).parent.parent / "data" / "results" / "rq3_association.json"
    if rq3_path.exists():
        with open(rq3_path) as f:
            rq3 = json.load(f)

        if "note" in rq3:
            st.info(f"ℹ️ {rq3['note']}")
        elif "base_model" in rq3:
            model = rq3["base_model"]
            st.write(f"**Model type:** {model.get('model_type', '—')}")
            st.write(f"**Observations:** {model.get('n_observations', '—')}")
            st.write(f"**Interpretation:** {model.get('interpretation', '—')}")

            coeffs = model.get("coefficients", {})
            if coeffs:
                st.markdown("**Coefficients:**")
                coeff_df = pd.DataFrame(coeffs).T
                st.dataframe(coeff_df, use_container_width=True)

        # Show correlation if available
        corr = rq3.get("correlation_matrix")
        if corr:
            st.markdown("**Correlation Matrix:**")
            st.dataframe(pd.DataFrame(corr), use_container_width=True)
    else:
        st.info(
            "Association analysis (count regression) will be run after "
            "maintenance events are extracted and the longitudinal dataset "
            "is constructed."
        )

    st.divider()
    st.subheader("RQ4 — Evolution Over Time")

    rq4_path = Path(__file__).parent.parent / "data" / "results" / "rq4_evolution.json"
    if rq4_path.exists():
        with open(rq4_path) as f:
            rq4 = json.load(f)

        case_studies = rq4.get("case_studies", [])
        if case_studies:
            st.write(f"**{len(case_studies)} repositories analyzed:**")
            for cs in case_studies:
                with st.expander(f"📦 {cs['repo_id']} — {cs['n_divergences']} divergences"):
                    st.write(f"**Categories:** {cs.get('categories', {})}")
                    st.write(f"**Env pairs:** {cs.get('env_pairs', {})}")
                    if "maintenance_events" in cs:
                        st.write(f"**Maintenance events:** {cs['maintenance_events']}")
                        st.write(f"**Corrective events:** {cs.get('corrective_events', 0)}")
                        st.write(f"**Event breakdown:** {cs.get('maintenance_categories', {})}")

        # Show temporal figure if available
        rq4_fig = Path(__file__).parent.parent / "data" / "results" / "figures" / "rq4_evolution.png"
        if rq4_fig.exists():
            st.image(str(rq4_fig), caption="Maintenance Event Patterns", use_container_width=True)
    else:
        st.info(
            "Temporal analysis will show divergence introduction, "
            "persistence, and resolution across snapshots."
        )


# ─────────────────────────────────────────────────────────────────────────────
# Tab 4: Data Quality
# ─────────────────────────────────────────────────────────────────────────────

with tab_quality:
    st.header("Data Quality & Limitations")

    # Parsing warnings
    if manifest:
        charts = manifest.get("chart_summaries", [])
        if charts:
            st.subheader("Chart Processing Summary")
            for cs in charts:
                name = cs.get("chart_name", "Unknown")
                envs = cs.get("environments", [])
                total = cs.get("total_divergences", 0)
                st.write(f"**{name}:** {len(envs)} environments, {total} divergences")

    # Redaction stats
    st.subheader("Secret Redaction")
    if "redacted" in df.columns:
        redacted_count = int(df["redacted"].sum())
        st.write(
            f"**{redacted_count}** out of **{len(df)}** divergence values "
            f"were redacted due to sensitive key patterns."
        )
    else:
        st.write("No redaction data available.")

    # Confidence distribution
    st.subheader("Confidence Assessment")
    if "confidence" in df.columns:
        conf_df = df["confidence"].value_counts().reset_index()
        conf_df.columns = ["Confidence", "Count"]
        st.dataframe(conf_df, use_container_width=True)

        medium_pct = (
            (df["confidence"] == "medium").sum() / len(df) * 100
            if len(df) > 0 else 0
        )
        if medium_pct > 50:
            st.warning(
                f"⚠️ {medium_pct:.0f}% of divergences have medium confidence. "
                f"This may indicate default-inheritance or array-matching "
                f"uncertainty. Manual review is recommended."
            )

    # Known limitations
    st.subheader("Known Limitations")
    limitations = [
        "Helm values merging is simplified (no subchart, no --set flags)",
        "Array comparison uses positional matching (no semantic container matching)",
        "Environment identification relies on naming conventions",
        "Kustomize rendering is not yet implemented",
        "Single-environment repos are compared against chart defaults only",
    ]
    for lim in limitations:
        st.write(f"- {lim}")

    # Pipeline version
    st.subheader("Reproducibility")
    if manifest:
        st.write(f"**Run ID:** {manifest.get('run_id', '—')}")
        st.write(f"**Start:** {manifest.get('run_start', '—')}")
        st.write(f"**Duration:** {manifest.get('duration_seconds', '—')}s")
        st.write(f"**Python:** {manifest.get('python_version', '—')}")


# ─────────────────────────────────────────────────────────────────────────────
# Sidebar — Study Info
# ─────────────────────────────────────────────────────────────────────────────

st.sidebar.divider()
st.sidebar.markdown("### Study Information")
st.sidebar.markdown(
    "This dashboard displays real outputs from the "
    "configuration divergence analysis pipeline. "
    "No data is hardcoded or simulated."
)
st.sidebar.markdown(
    "**Key distinction:** Category labels indicate the *type* "
    "of difference, not intent. Classification as intentional "
    "or accidental requires human review."
)
st.sidebar.markdown("---")
st.sidebar.markdown("v0.1.0 · Research Use Only")
