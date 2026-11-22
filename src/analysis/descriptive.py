"""
Descriptive statistics for RQ1.

Generates:
- Divergence frequency distributions
- Category breakdowns
- Repository-level comparisons
- Environment-pair comparisons
- Summary tables suitable for academic reporting
"""
from typing import Any

import pandas as pd
import numpy as np

from src.utils.logging_config import get_logger

logger = get_logger("descriptive")


def describe_divergence_distribution(
    divergences: pd.DataFrame,
) -> dict[str, Any]:
    """
    Compute descriptive statistics for the overall divergence distribution.

    Returns summary stats suitable for a results section.
    """
    if divergences.empty:
        return {"n": 0, "note": "No divergence data available"}

    n = len(divergences)
    repos = divergences["repo_id"].nunique() if "repo_id" in divergences.columns else 0

    result = {
        "n_divergences": n,
        "n_repositories": repos,
    }

    # Category distribution
    if "category" in divergences.columns:
        cat_dist = divergences["category"].value_counts()
        result["category_distribution"] = cat_dist.to_dict()
        result["category_proportions"] = (cat_dist / n).round(4).to_dict()
        result["n_categories"] = len(cat_dist)
        result["most_common_category"] = cat_dist.index[0]

    # Diff type distribution
    if "diff_type" in divergences.columns:
        type_dist = divergences["diff_type"].value_counts()
        result["diff_type_distribution"] = type_dist.to_dict()

    # Confidence distribution
    if "confidence" in divergences.columns:
        conf_dist = divergences["confidence"].value_counts()
        result["confidence_distribution"] = conf_dist.to_dict()

    # Default inheritance
    if "is_from_default" in divergences.columns:
        from_default = divergences["is_from_default"].sum()
        result["from_default_count"] = int(from_default)
        result["from_default_proportion"] = round(from_default / n, 4)

    # Per-repository summary
    if "repo_id" in divergences.columns:
        per_repo = divergences.groupby("repo_id").agg(
            n_divergences=("divergence_id", "count"),
            n_categories=("category", "nunique"),
        )
        result["per_repo_summary"] = {
            "mean_divergences": round(per_repo["n_divergences"].mean(), 2),
            "median_divergences": round(per_repo["n_divergences"].median(), 2),
            "std_divergences": round(per_repo["n_divergences"].std(), 2),
            "min_divergences": int(per_repo["n_divergences"].min()),
            "max_divergences": int(per_repo["n_divergences"].max()),
            "mean_categories": round(per_repo["n_categories"].mean(), 2),
        }

    return result


def describe_density_distribution(
    analysis_dataset: pd.DataFrame,
) -> dict[str, Any]:
    """
    Descriptive statistics for divergence density across repo-snapshots.
    """
    if analysis_dataset.empty:
        return {"n": 0}

    result = {"n_observations": len(analysis_dataset)}

    for col in ["raw_divergence_density", "raw_divergence_count",
                "maintenance_event_count", "corrective_event_count"]:
        if col in analysis_dataset.columns:
            series = analysis_dataset[col].dropna()
            result[f"{col}_stats"] = {
                "mean": round(float(series.mean()), 4),
                "median": round(float(series.median()), 4),
                "std": round(float(series.std()), 4),
                "min": round(float(series.min()), 4),
                "max": round(float(series.max()), 4),
                "q25": round(float(series.quantile(0.25)), 4),
                "q75": round(float(series.quantile(0.75)), 4),
                "skewness": round(float(series.skew()), 4) if len(series) > 2 else None,
            }

    return result


def generate_summary_table(
    divergences: pd.DataFrame,
    group_by: str = "category",
) -> pd.DataFrame:
    """
    Generate a formatted summary table grouped by a column.

    Suitable for inclusion in a research paper.
    """
    if divergences.empty:
        return pd.DataFrame()

    agg_dict = {
        "divergence_id": "count",
    }
    rename_dict = {"divergence_id": "Count"}

    if "confidence" in divergences.columns:
        # Count high-confidence cases
        divergences = divergences.copy()
        divergences["_high_conf"] = divergences["confidence"] == "high"
        agg_dict["_high_conf"] = "sum"
        rename_dict["_high_conf"] = "High Confidence"

    if "is_from_default" in divergences.columns:
        agg_dict["is_from_default"] = "sum"
        rename_dict["is_from_default"] = "From Default"

    table = divergences.groupby(group_by).agg(agg_dict).rename(columns=rename_dict)
    table["Proportion"] = (table["Count"] / table["Count"].sum()).round(4)
    table = table.sort_values("Count", ascending=False)

    return table
