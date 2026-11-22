"""
Stage 6: Longitudinal Analysis & Full Statistical Pipeline

1. Build repository metadata table
2. Construct longitudinal analysis dataset
3. Run RQ1 descriptive statistics
4. Run RQ3 count regression (association analysis)
5. Run robustness checks
6. Generate publication-quality figures
7. Save all results
"""
import sys
import json
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).parent))

import pandas as pd
import numpy as np

from src.analysis.descriptive import (
    describe_divergence_distribution,
    describe_density_distribution,
    generate_summary_table,
)
from src.analysis.inferential import test_association, run_robustness_checks
from src.longitudinal.dataset import build_analysis_dataset, validate_temporal_ordering
from src.utils.logging_config import setup_logging, get_logger

setup_logging(level="INFO", log_dir="data/logs")
logger = get_logger("stage6")

PROJECT_DIR = Path(__file__).parent
DATA_DIR = PROJECT_DIR / "data"
OUTPUTS_DIR = DATA_DIR / "outputs"
PROCESSED_DIR = DATA_DIR / "processed"
RESULTS_DIR = DATA_DIR / "results"
FIGURES_DIR = RESULTS_DIR / "figures"

RESULTS_DIR.mkdir(parents=True, exist_ok=True)
FIGURES_DIR.mkdir(parents=True, exist_ok=True)


# ───────────────────────────────────────────────────────────────────────
# Part 1: Build repository metadata
# ───────────────────────────────────────────────────────────────────────

def build_repo_metadata():
    """Build repository metadata from pipeline manifests and git data."""
    repos = []
    for run_dir in OUTPUTS_DIR.iterdir():
        if not run_dir.is_dir() or run_dir.name == "fixtures":
            continue

        manifest_path = run_dir / "run_manifest.json"
        if not manifest_path.exists():
            continue

        with open(manifest_path) as f:
            manifest = json.load(f)

        repo_id = manifest.get("repo_id", run_dir.name)

        # Get dates from maintenance events if available
        events_path = PROCESSED_DIR / "maintenance_events.csv"
        first_commit = None
        last_commit = None
        if events_path.exists():
            events_df = pd.read_csv(events_path)
            repo_events = events_df[events_df["repo_id"] == repo_id]
            if not repo_events.empty and "event_date" in repo_events.columns:
                dates = pd.to_datetime(repo_events["event_date"], utc=True, errors="coerce").dropna()
                if not dates.empty:
                    first_commit = dates.min().isoformat()
                    last_commit = dates.max().isoformat()

        envs = []
        for cs in manifest.get("chart_summaries", []):
            envs.extend(cs.get("environments", []))

        repos.append({
            "repo_id": repo_id,
            "repo_dir": run_dir.name,
            "stars": 0,  # Could be enriched from GitHub API
            "contributors": 0,
            "environments_detected": ",".join(set(envs)),
            "first_commit_date": first_commit,
            "last_commit_date": last_commit,
            "charts_analyzed": manifest.get("charts_with_envs", 0),
            "total_divergences": manifest.get("total_divergences", 0),
            "total_comparable_paths": manifest.get("total_comparable_paths", 0),
        })

    df = pd.DataFrame(repos)
    meta_path = PROCESSED_DIR / "repository_metadata.csv"
    df.to_csv(meta_path, index=False)
    logger.info(f"Built metadata for {len(df)} repos -> {meta_path}")
    return df


# ───────────────────────────────────────────────────────────────────────
# Part 2: Build snapshot records
# ───────────────────────────────────────────────────────────────────────

def build_snapshots():
    """Build snapshot records from pipeline runs."""
    snapshots = []
    for run_dir in OUTPUTS_DIR.iterdir():
        if not run_dir.is_dir() or run_dir.name == "fixtures":
            continue

        manifest_path = run_dir / "run_manifest.json"
        if not manifest_path.exists():
            continue

        with open(manifest_path) as f:
            manifest = json.load(f)

        snapshots.append({
            "snapshot_id": manifest.get("run_id", run_dir.name),
            "repo_id": manifest.get("repo_id", run_dir.name),
            "commit_sha": manifest.get("commit_sha", "HEAD"),
            "commit_date": manifest.get("run_start", datetime.now(timezone.utc).isoformat()),
            "total_comparable_paths": manifest.get("total_comparable_paths", 0),
        })

    df = pd.DataFrame(snapshots)
    snap_path = PROCESSED_DIR / "snapshots.csv"
    df.to_csv(snap_path, index=False)
    logger.info(f"Built {len(df)} snapshot records -> {snap_path}")
    return df


# ───────────────────────────────────────────────────────────────────────
# Part 3: RQ1 Descriptive Statistics
# ───────────────────────────────────────────────────────────────────────

def run_rq1_analysis(divergences_df):
    """Run RQ1 descriptive analysis and generate figures."""
    logger.info("Running RQ1 descriptive analysis...")

    # Basic distribution
    dist_stats = describe_divergence_distribution(divergences_df)

    # Summary table by category
    cat_table = generate_summary_table(divergences_df, group_by="category")

    # Save results
    rq1_results = {
        "research_question": "RQ1: What types of configuration divergence occur across environments?",
        "distribution_stats": dist_stats,
        "category_table": cat_table.to_dict() if not cat_table.empty else {},
    }

    rq1_path = RESULTS_DIR / "rq1_descriptive.json"
    with open(rq1_path, "w", encoding="utf-8") as f:
        json.dump(rq1_results, f, indent=2, default=str)

    if not cat_table.empty:
        cat_table.to_csv(RESULTS_DIR / "rq1_category_table.csv")

    logger.info(f"RQ1 results saved to {rq1_path}")

    # Generate figure
    _generate_rq1_figure(divergences_df, dist_stats)

    return rq1_results


def _generate_rq1_figure(df, stats):
    """Generate publication-quality RQ1 figure."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        fig, axes = plt.subplots(2, 2, figsize=(14, 10))
        fig.suptitle(
            "RQ1: Configuration Divergence Distribution",
            fontsize=14, fontweight="bold",
        )

        # 1. Category distribution
        ax1 = axes[0, 0]
        if "category" in df.columns:
            cat_counts = df["category"].value_counts()
            colors = []
            from src.divergence.taxonomy import is_typically_env_specific
            for cat in cat_counts.index:
                typically = is_typically_env_specific(cat)
                colors.append("#4CAF50" if typically else "#FF9800")

            ax1.barh(cat_counts.index, cat_counts.values, color=colors)
            ax1.set_xlabel("Count")
            ax1.set_title("(a) Divergences by Category")
            ax1.invert_yaxis()

        # 2. Diff type distribution
        ax2 = axes[0, 1]
        if "diff_type" in df.columns:
            type_counts = df["diff_type"].value_counts()
            ax2.pie(
                type_counts.values, labels=type_counts.index,
                autopct="%1.0f%%", startangle=90,
                colors=["#2196F3", "#FF9800", "#4CAF50", "#F44336"],
            )
            ax2.set_title("(b) Difference Types")

        # 3. Confidence distribution
        ax3 = axes[1, 0]
        if "confidence" in df.columns:
            conf_counts = df["confidence"].value_counts()
            ax3.bar(conf_counts.index, conf_counts.values,
                    color=["#4CAF50", "#FFC107", "#F44336"][:len(conf_counts)])
            ax3.set_xlabel("Confidence Level")
            ax3.set_ylabel("Count")
            ax3.set_title("(c) Confidence Distribution")

        # 4. Per-repo divergence counts
        ax4 = axes[1, 1]
        if "repo_id" in df.columns:
            repo_counts = df["repo_id"].value_counts()
            ax4.barh(repo_counts.index, repo_counts.values, color="#607D8B")
            ax4.set_xlabel("Number of Divergences")
            ax4.set_title("(d) Divergences per Repository")
            ax4.invert_yaxis()

        plt.tight_layout()
        fig_path = FIGURES_DIR / "rq1_distribution.png"
        plt.savefig(fig_path, dpi=300, bbox_inches="tight")
        plt.close()
        logger.info(f"RQ1 figure saved to {fig_path}")
    except Exception as e:
        logger.warning(f"RQ1 figure generation failed: {e}")


# ───────────────────────────────────────────────────────────────────────
# Part 4: RQ2 Classification Results
# ───────────────────────────────────────────────────────────────────────

def run_rq2_analysis():
    """Compile RQ2 classification results from Stage 5 outputs."""
    agreement_path = PROCESSED_DIR / "agreement_report.json"
    annotations_path = PROCESSED_DIR / "annotations.csv"

    rq2_results = {
        "research_question": (
            "RQ2: How reliably can independent reviewers classify "
            "intentional vs accidental divergence?"
        ),
    }

    if agreement_path.exists():
        with open(agreement_path) as f:
            report = json.load(f)
        rq2_results["agreement_report"] = report
        rq2_results["kappa"] = report.get("kappa")
        rq2_results["raw_agreement"] = report.get("raw_agreement")
        rq2_results["interpretation"] = _interpret_kappa(report.get("kappa"))

    if annotations_path.exists():
        annotations = pd.read_csv(annotations_path)
        # Label distribution per reviewer
        for reviewer in annotations["reviewer_id"].unique():
            r_labels = annotations[annotations["reviewer_id"] == reviewer]
            rq2_results[f"label_distribution_{reviewer}"] = (
                r_labels["label"].value_counts().to_dict()
            )

    rq2_path = RESULTS_DIR / "rq2_classification.json"
    with open(rq2_path, "w", encoding="utf-8") as f:
        json.dump(rq2_results, f, indent=2, default=str)

    logger.info(f"RQ2 results saved to {rq2_path}")
    return rq2_results


def _interpret_kappa(kappa):
    """Interpret Cohen's kappa value using Landis & Koch scale."""
    if kappa is None:
        return "No kappa computed"
    if kappa < 0:
        return "Less than chance agreement"
    if kappa < 0.21:
        return "Slight agreement (Landis & Koch)"
    if kappa < 0.41:
        return "Fair agreement"
    if kappa < 0.61:
        return "Moderate agreement"
    if kappa < 0.81:
        return "Substantial agreement"
    return "Almost perfect agreement"


# ───────────────────────────────────────────────────────────────────────
# Part 5: RQ3 Association Analysis
# ───────────────────────────────────────────────────────────────────────

def run_rq3_analysis(analysis_dataset):
    """Run RQ3 count regression and robustness checks."""
    rq3_results = {
        "research_question": (
            "RQ3: Is higher accidental divergence associated with "
            "subsequent maintenance activity?"
        ),
    }

    if analysis_dataset.empty or len(analysis_dataset) < 2:
        rq3_results["note"] = (
            f"Insufficient observations ({len(analysis_dataset)}) for regression. "
            f"Minimum 5 required. Descriptive comparison reported instead."
        )

        # Descriptive comparison when regression isn't possible
        if not analysis_dataset.empty:
            density_stats = describe_density_distribution(analysis_dataset)
            rq3_results["density_stats"] = density_stats

            # Simple correlation if we have enough data
            if len(analysis_dataset) >= 2:
                corr_cols = ["raw_divergence_count", "raw_divergence_density",
                             "maintenance_event_count", "corrective_event_count"]
                available = [c for c in corr_cols if c in analysis_dataset.columns]
                if len(available) >= 2:
                    corr_matrix = analysis_dataset[available].corr()
                    rq3_results["correlation_matrix"] = corr_matrix.to_dict()

        rq3_path = RESULTS_DIR / "rq3_association.json"
        with open(rq3_path, "w", encoding="utf-8") as f:
            json.dump(rq3_results, f, indent=2, default=str)
        logger.info(f"RQ3 results (descriptive only) saved to {rq3_path}")
        return rq3_results

    # Full regression analysis
    base_result = test_association(
        analysis_dataset,
        predictor="raw_divergence_density",
        outcome="maintenance_event_count",
    )
    rq3_results["base_model"] = base_result

    # Robustness checks
    robustness = run_robustness_checks(
        analysis_dataset,
        predictor="raw_divergence_density",
        outcome="maintenance_event_count",
    )
    rq3_results["robustness_checks"] = robustness

    rq3_path = RESULTS_DIR / "rq3_association.json"
    with open(rq3_path, "w", encoding="utf-8") as f:
        json.dump(rq3_results, f, indent=2, default=str)

    logger.info(f"RQ3 results saved to {rq3_path}")
    return rq3_results


# ───────────────────────────────────────────────────────────────────────
# Part 6: RQ4 Evolution Analysis
# ───────────────────────────────────────────────────────────────────────

def run_rq4_analysis(divergences_df, events_df):
    """Run RQ4 temporal evolution analysis."""
    rq4_results = {
        "research_question": (
            "RQ4: How does divergence evolve over time?"
        ),
    }

    # With limited snapshots, provide case study analysis
    if divergences_df.empty:
        rq4_results["note"] = "No divergence data available"
        rq4_path = RESULTS_DIR / "rq4_evolution.json"
        with open(rq4_path, "w", encoding="utf-8") as f:
            json.dump(rq4_results, f, indent=2, default=str)
        return rq4_results

    # Case studies: select repos with most divergences
    case_studies = []
    for repo_id, group in divergences_df.groupby("repo_id"):
        study = {
            "repo_id": repo_id,
            "n_divergences": len(group),
            "categories": group["category"].value_counts().to_dict(),
            "env_pairs": group["env_pair"].value_counts().to_dict() if "env_pair" in group.columns else {},
            "confidence_distribution": group["confidence"].value_counts().to_dict() if "confidence" in group.columns else {},
            "from_default_rate": float(group["is_from_default"].mean()) if "is_from_default" in group.columns else None,
        }

        # Add maintenance context if available
        if not events_df.empty:
            repo_events = events_df[events_df["repo_id"] == repo_id]
            if not repo_events.empty:
                study["maintenance_events"] = len(repo_events)
                study["maintenance_categories"] = repo_events["category"].value_counts().to_dict()
                study["corrective_events"] = int(
                    repo_events["category"].isin(["corrective_fix", "sync", "rework"]).sum()
                )

        case_studies.append(study)

    rq4_results["case_studies"] = case_studies
    rq4_results["n_repos"] = len(case_studies)

    # Temporal patterns from maintenance events
    if not events_df.empty and "event_date" in events_df.columns:
        events_df = events_df.copy()
        events_df["event_date_dt"] = pd.to_datetime(events_df["event_date"], utc=True, errors="coerce")
        events_df = events_df.dropna(subset=["event_date_dt"])

        if not events_df.empty:
            # Monthly event counts
            events_df["month"] = events_df["event_date_dt"].dt.tz_localize(None).dt.to_period("M").astype(str)
            monthly = events_df.groupby(["repo_id", "month", "category"]).size().reset_index(name="count")
            rq4_results["monthly_event_counts"] = monthly.to_dict(orient="records")

            # Generate temporal figure
            _generate_rq4_figure(events_df)

    rq4_path = RESULTS_DIR / "rq4_evolution.json"
    with open(rq4_path, "w", encoding="utf-8") as f:
        json.dump(rq4_results, f, indent=2, default=str)

    logger.info(f"RQ4 results saved to {rq4_path}")
    return rq4_results


def _generate_rq4_figure(events_df):
    """Generate temporal evolution figure."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        fig, axes = plt.subplots(1, 2, figsize=(14, 6))
        fig.suptitle(
            "RQ4: Configuration Maintenance Event Patterns",
            fontsize=14, fontweight="bold",
        )

        # 1. Event category distribution
        ax1 = axes[0]
        cat_counts = events_df["category"].value_counts()
        colors_map = {
            "corrective_fix": "#F44336",
            "sync": "#FF9800",
            "rework": "#FF5722",
            "resource_tune": "#2196F3",
            "routine": "#4CAF50",
            "unrelated": "#9E9E9E",
        }
        colors = [colors_map.get(c, "#607D8B") for c in cat_counts.index]
        ax1.barh(cat_counts.index, cat_counts.values, color=colors)
        ax1.set_xlabel("Number of Events")
        ax1.set_title("(a) Maintenance Events by Category")
        ax1.invert_yaxis()

        # 2. Monthly timeline (all repos stacked)
        ax2 = axes[1]
        events_df["month"] = events_df["event_date_dt"].dt.tz_localize(None).dt.to_period("M")
        monthly = events_df.groupby("month").size()
        if len(monthly) > 1:
            x_labels = [str(m) for m in monthly.index]
            # Show at most 24 months
            if len(x_labels) > 24:
                step = len(x_labels) // 24
                x_labels_display = [x_labels[i] if i % step == 0 else "" for i in range(len(x_labels))]
            else:
                x_labels_display = x_labels
            ax2.bar(range(len(monthly)), monthly.values, color="#607D8B")
            ax2.set_xticks(range(len(x_labels_display)))
            ax2.set_xticklabels(x_labels_display, rotation=45, ha="right", fontsize=7)
            ax2.set_xlabel("Month")
            ax2.set_ylabel("Events")
            ax2.set_title("(b) Monthly Maintenance Events")
        else:
            ax2.text(0.5, 0.5, "Insufficient temporal data",
                    ha="center", va="center", transform=ax2.transAxes)
            ax2.set_title("(b) Monthly Timeline")

        plt.tight_layout()
        fig_path = FIGURES_DIR / "rq4_evolution.png"
        plt.savefig(fig_path, dpi=300, bbox_inches="tight")
        plt.close()
        logger.info(f"RQ4 figure saved to {fig_path}")
    except Exception as e:
        logger.warning(f"RQ4 figure generation failed: {e}")


# ───────────────────────────────────────────────────────────────────────
# Main
# ───────────────────────────────────────────────────────────────────────

def main():
    print("=" * 70)
    print("  STAGE 6: Longitudinal Analysis & Full Statistical Pipeline")
    print("=" * 70)

    # 1. Build metadata
    print("\n[1/7] Building repository metadata...")
    repo_meta = build_repo_metadata()

    # 2. Build snapshots
    print("\n[2/7] Building snapshot records...")
    snapshots = build_snapshots()

    # 3. Load divergences
    print("\n[3/7] Loading divergence data...")
    div_path = PROCESSED_DIR / "all_divergences.csv"
    if not div_path.exists():
        # Merge from outputs
        from run_stage5 import merge_divergences
        divergences = merge_divergences()
    else:
        divergences = pd.read_csv(div_path)
    logger.info(f"Loaded {len(divergences)} divergences")

    # 4. Load maintenance events
    events_path = PROCESSED_DIR / "maintenance_events.csv"
    events_df = pd.DataFrame()
    if events_path.exists():
        events_df = pd.read_csv(events_path)
        logger.info(f"Loaded {len(events_df)} maintenance events")

    # 5. Build analysis dataset
    print("\n[4/7] Building longitudinal analysis dataset...")
    analysis_dataset = build_analysis_dataset(
        snapshots=snapshots,
        divergences=divergences,
        maintenance_events=events_df,
        repositories=repo_meta,
        window_days=90,
        min_post_snapshot_days=30,
    )

    # Validate
    validation = validate_temporal_ordering(analysis_dataset)
    logger.info(f"Temporal validation: {validation}")

    analysis_path = PROCESSED_DIR / "analysis_dataset.csv"
    if not analysis_dataset.empty:
        analysis_dataset.to_csv(analysis_path, index=False)
        logger.info(f"Analysis dataset: {len(analysis_dataset)} records -> {analysis_path}")

    # 6. Run all RQ analyses
    print("\n[5/7] RQ1: Descriptive statistics...")
    rq1 = run_rq1_analysis(divergences)

    print("\n[6/7] RQ2: Classification results...")
    rq2 = run_rq2_analysis()

    print("\n[7/7] RQ3-4: Association & Evolution...")
    rq3 = run_rq3_analysis(analysis_dataset)
    rq4 = run_rq4_analysis(divergences, events_df)

    # Summary
    print("\n" + "=" * 70)
    print("  STAGE 6 COMPLETE")
    print("=" * 70)
    print(f"  Repositories:         {len(repo_meta)}")
    print(f"  Snapshots:            {len(snapshots)}")
    print(f"  Analysis records:     {len(analysis_dataset)}")
    print(f"  RQ1 categories:       {rq1.get('distribution_stats', {}).get('n_categories', 0)}")
    print(f"  RQ2 kappa:            {rq2.get('kappa', 'N/A')}")
    print(f"  RQ3 model:            {rq3.get('base_model', {}).get('model_type', rq3.get('note', 'N/A'))}")
    print(f"  RQ4 case studies:     {rq4.get('n_repos', 0)}")
    print(f"  Figures:              {list(FIGURES_DIR.glob('*.png'))}")
    print("=" * 70)


if __name__ == "__main__":
    main()
