"""
End-to-end pipeline runner for the vertical slice.

Processes a single Helm repository:
1. Discovers chart directories
2. Identifies environment-specific values files
3. Parses defaults and environment values
4. Extracts divergences with taxonomy classification
5. Computes metrics
6. Saves structured output (CSV)
7. Generates a summary figure
8. Logs a reproducible execution manifest

Usage:
    python run_pipeline.py --repo-path <path> --repo-id <owner/name>
    python run_pipeline.py --fixtures   # Run against test fixtures
"""
import argparse
import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

# Ensure src is importable
sys.path.insert(0, str(Path(__file__).parent))

from src.utils.logging_config import setup_logging, get_logger
from src.parsing.helm import discover_chart_directories, parse_helm_chart
from src.divergence.extractor import extract_divergences, compute_snapshot_summary
from src.divergence.metrics import compute_snapshot_metrics, summarize_by_category, summarize_by_env_pair


def run_pipeline(
    repo_path: Path,
    repo_id: str,
    output_dir: Path,
    commit_sha: str = "HEAD",
    file_list: list[str] | None = None,
    file_reader=None,
) -> dict:
    """
    Execute the full analysis pipeline on a single repository.

    Args:
        repo_path: Path to the repository root (or fixtures directory).
        repo_id: Repository identifier (e.g., 'owner/repo').
        output_dir: Directory for output CSV and figures.
        commit_sha: Git commit SHA or 'HEAD'.
        file_list: Pre-computed file list (optional).
        file_reader: Custom file reader function (optional).

    Returns:
        Dict with execution summary.
    """
    logger = get_logger("pipeline")
    run_id = str(uuid.uuid4())[:8]
    run_start = datetime.now(timezone.utc)

    logger.info(f"=== Pipeline run {run_id} started ===")
    logger.info(f"Repository: {repo_id} at {repo_path}")

    # Ensure output directory exists
    output_dir.mkdir(parents=True, exist_ok=True)

    # Step 1: Discover files
    if file_list is None:
        logger.info("Scanning filesystem for files...")
        file_list = []
        for f in repo_path.rglob("*"):
            if f.is_file():
                rel = str(f.relative_to(repo_path)).replace("\\", "/")
                file_list.append(rel)

    logger.info(f"Found {len(file_list)} files")

    # Step 2: Discover chart directories
    chart_dirs = discover_chart_directories(repo_path, file_list)
    logger.info(f"Found {len(chart_dirs)} chart directories: {chart_dirs}")

    if not chart_dirs:
        logger.warning("No Helm charts found in repository")
        return {"status": "no_charts", "charts_found": 0}

    # Step 3-4: Parse charts and extract divergences
    all_divergences = []
    chart_summaries = []

    for chart_dir in chart_dirs:
        logger.info(f"Processing chart at: {chart_dir or '(root)'}")

        chart = parse_helm_chart(
            repo_path=repo_path,
            chart_dir=chart_dir,
            file_list=file_list,
            file_reader=file_reader,
            redact_secrets=True,
        )

        if chart is None:
            logger.info(f"  Skipped (no environment-specific values)")
            continue

        logger.info(f"  Chart: {chart.name}")
        logger.info(f"  Environments: {chart.environments}")
        if chart.parse_warnings:
            for w in chart.parse_warnings:
                logger.warning(f"  Warning: {w}")

        # Extract divergences
        divergences = extract_divergences(
            chart=chart,
            repo_id=repo_id,
            commit_sha=commit_sha,
            commit_date=run_start.isoformat(),
        )

        logger.info(f"  Divergences found: {len(divergences)}")

        # Compute snapshot summary
        summary = compute_snapshot_summary(divergences)
        summary["chart_name"] = chart.name
        summary["chart_path"] = chart_dir
        summary["environments"] = chart.environments
        chart_summaries.append(summary)

        all_divergences.extend(divergences)

    if not all_divergences:
        logger.warning("No divergences found in any chart")
        return {
            "status": "no_divergences",
            "charts_found": len(chart_dirs),
            "charts_with_envs": len(chart_summaries),
        }

    # Step 5: Create DataFrame and compute metrics
    df = pd.DataFrame(all_divergences)
    total_paths = df["total_comparable_paths"].max() if not df.empty else 0

    metrics = compute_snapshot_metrics(df, total_paths)
    cat_summary = summarize_by_category(df)
    pair_summary = summarize_by_env_pair(df, total_paths)

    # Step 6: Save outputs
    # Divergence records
    csv_path = output_dir / "divergences.csv"
    df.to_csv(csv_path, index=False)
    logger.info(f"Saved {len(df)} divergence records to {csv_path}")

    # Category summary
    cat_csv = output_dir / "category_summary.csv"
    cat_summary.to_csv(cat_csv, index=False)
    logger.info(f"Saved category summary to {cat_csv}")

    # Environment pair summary
    pair_csv = output_dir / "env_pair_summary.csv"
    pair_summary.to_csv(pair_csv, index=False)
    logger.info(f"Saved env pair summary to {pair_csv}")

    # Metrics JSON
    metrics_path = output_dir / "snapshot_metrics.json"
    with open(metrics_path, "w", encoding="utf-8") as f:
        json.dump(metrics, f, indent=2, default=str)
    logger.info(f"Saved metrics to {metrics_path}")

    # Step 7: Generate figure
    fig_path = _generate_figure(df, cat_summary, output_dir, repo_id)

    # Step 8: Execution manifest
    run_end = datetime.now(timezone.utc)
    manifest = {
        "run_id": run_id,
        "repo_id": repo_id,
        "repo_path": str(repo_path),
        "commit_sha": commit_sha,
        "run_start": run_start.isoformat(),
        "run_end": run_end.isoformat(),
        "duration_seconds": (run_end - run_start).total_seconds(),
        "python_version": sys.version,
        "charts_found": len(chart_dirs),
        "charts_with_envs": len(chart_summaries),
        "total_divergences": len(df),
        "total_comparable_paths": total_paths,
        "raw_divergence_density": metrics["raw_divergence_density"],
        "categories_found": list(metrics["category_counts"].keys()),
        "output_files": [
            str(csv_path),
            str(cat_csv),
            str(pair_csv),
            str(metrics_path),
            str(fig_path) if fig_path else None,
        ],
        "chart_summaries": chart_summaries,
    }

    manifest_path = output_dir / "run_manifest.json"
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, default=str)
    logger.info(f"Saved manifest to {manifest_path}")

    # Print summary
    _print_summary(metrics, cat_summary, pair_summary, repo_id, len(df))

    logger.info(f"=== Pipeline run {run_id} complete ({manifest['duration_seconds']:.1f}s) ===")
    return manifest


def _generate_figure(
    df: pd.DataFrame,
    cat_summary: pd.DataFrame,
    output_dir: Path,
    repo_id: str,
) -> Path | None:
    """Generate a divergence category distribution figure."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        fig, axes = plt.subplots(1, 2, figsize=(14, 6))
        fig.suptitle(
            f"Configuration Divergence Analysis: {repo_id}",
            fontsize=14, fontweight="bold",
        )

        # Left: Category distribution bar chart
        ax1 = axes[0]
        if not cat_summary.empty:
            colors = []
            for _, row in cat_summary.iterrows():
                if row.get("typically_env_specific") is True:
                    colors.append("#4CAF50")  # Green = typically intentional
                elif row.get("typically_env_specific") is False:
                    colors.append("#FF9800")  # Orange = warrants attention
                else:
                    colors.append("#9E9E9E")  # Gray = unknown
            ax1.barh(
                cat_summary["category"],
                cat_summary["count"],
                color=colors,
            )
            ax1.set_xlabel("Number of Divergences")
            ax1.set_title("Divergences by Category")
            ax1.invert_yaxis()

            # Legend
            from matplotlib.patches import Patch
            legend_elements = [
                Patch(facecolor="#4CAF50", label="Typically env-specific"),
                Patch(facecolor="#FF9800", label="Warrants attention"),
                Patch(facecolor="#9E9E9E", label="Uncategorized"),
            ]
            ax1.legend(handles=legend_elements, loc="lower right", fontsize=8)

        # Right: Diff type distribution
        ax2 = axes[1]
        if "diff_type" in df.columns:
            type_counts = df["diff_type"].value_counts()
            ax2.pie(
                type_counts.values,
                labels=type_counts.index,
                autopct="%1.0f%%",
                startangle=90,
            )
            ax2.set_title("Difference Types")

        plt.tight_layout()
        fig_path = output_dir / "divergence_analysis.png"
        plt.savefig(fig_path, dpi=150, bbox_inches="tight")
        plt.close()
        return fig_path
    except ImportError:
        logger.warning("matplotlib not available — skipping figure generation")
        return None
    except Exception as e:
        logger.warning(f"Figure generation failed: {e}")
        return None


def _print_summary(metrics, cat_summary, pair_summary, repo_id, total):
    """Print a human-readable analysis summary."""
    print("\n" + "=" * 70)
    print(f"  DIVERGENCE ANALYSIS SUMMARY: {repo_id}")
    print("=" * 70)
    print(f"  Total divergences:       {metrics['raw_divergence_count']}")
    print(f"  Comparable paths:        {metrics['total_comparable_paths']}")
    print(f"  Raw divergence density:  {metrics['raw_divergence_density']:.4f}")
    print(f"  High confidence:         {metrics['high_confidence_count']}")
    print(f"  From defaults:           {metrics['from_default_count']}")
    print(f"  Typically env-specific:  {metrics['typically_env_specific_count']}")
    print()
    print("  Category Breakdown:")
    for cat, count in sorted(
        metrics["category_counts"].items(), key=lambda x: -x[1]
    ):
        density = metrics["category_densities"].get(cat, 0)
        print(f"    {cat:30s}  {count:4d}  (density: {density:.4f})")
    print()
    if not pair_summary.empty:
        print("  Environment Pair Breakdown:")
        for _, row in pair_summary.iterrows():
            print(f"    {row['env_pair']:30s}  {row['count']:4d}  (density: {row['density']:.4f})")
    print("=" * 70 + "\n")


def main():
    parser = argparse.ArgumentParser(
        description="Run configuration divergence analysis pipeline"
    )
    parser.add_argument(
        "--repo-path", type=str,
        help="Path to the repository root",
    )
    parser.add_argument(
        "--repo-id", type=str, default="local/repo",
        help="Repository identifier (e.g., owner/repo)",
    )
    parser.add_argument(
        "--output-dir", type=str, default="data/outputs",
        help="Output directory for results",
    )
    parser.add_argument(
        "--fixtures", action="store_true",
        help="Run against test fixtures instead of a real repo",
    )
    parser.add_argument(
        "--log-level", type=str, default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
    )

    args = parser.parse_args()
    setup_logging(level=args.log_level, log_dir="data/logs")

    if args.fixtures:
        repo_path = Path(__file__).parent / "tests" / "fixtures" / "helm_chart"
        repo_id = "test/sample-webapp"
        output_dir = Path(__file__).parent / "data" / "outputs" / "fixtures"
    else:
        if not args.repo_path:
            parser.error("--repo-path is required unless --fixtures is used")
        repo_path = Path(args.repo_path)
        repo_id = args.repo_id
        output_dir = Path(args.output_dir)

    if not repo_path.exists():
        print(f"Error: Repository path does not exist: {repo_path}")
        sys.exit(1)

    result = run_pipeline(
        repo_path=repo_path,
        repo_id=repo_id,
        output_dir=output_dir,
    )

    if result.get("status") in ("no_charts", "no_divergences"):
        print(f"Pipeline completed with status: {result['status']}")
        sys.exit(0)

    print(f"Pipeline complete. Output: {output_dir}")


if __name__ == "__main__":
    main()
