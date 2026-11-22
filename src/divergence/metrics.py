"""
Divergence measurement framework.

Computes independently interpretable metrics from divergence records.
Every formula, denominator, and aggregation rule is documented.

Metrics are computed at three levels:
1. Snapshot level (single point in time)
2. Environment-pair level
3. Repository level (aggregated across snapshots)

Raw and evidence-based measurements are always kept separate.
"""
from typing import Any

import pandas as pd

from src.utils.logging_config import get_logger

logger = get_logger("metrics")


def compute_snapshot_metrics(
    divergences: pd.DataFrame,
    total_comparable_paths: int,
) -> dict[str, Any]:
    """
    Compute divergence metrics for a single snapshot.

    Formulas:
    - raw_divergence_count: total number of raw differences
    - raw_divergence_density: raw_divergence_count / total_comparable_paths
    - category_counts: count of divergences per taxonomy category
    - category_densities: each category count / total_comparable_paths
    - high_confidence_count: divergences with confidence='high'
    - from_default_count: divergences involving inherited defaults
    - typically_env_specific_count: divergences in typically-varying categories

    Args:
        divergences: DataFrame of divergence records for one snapshot.
        total_comparable_paths: Denominator for density (union of all paths).

    Returns:
        Dict of metric name -> value.
    """
    if divergences.empty or total_comparable_paths == 0:
        return {
            "raw_divergence_count": 0,
            "raw_divergence_density": 0.0,
            "category_counts": {},
            "category_densities": {},
            "high_confidence_count": 0,
            "from_default_count": 0,
            "typically_env_specific_count": 0,
            "total_comparable_paths": total_comparable_paths,
        }

    n = len(divergences)
    density = n / total_comparable_paths

    # Category breakdown
    cat_counts = divergences["category"].value_counts().to_dict()
    cat_densities = {
        cat: count / total_comparable_paths
        for cat, count in cat_counts.items()
    }

    # Confidence breakdown
    high_conf = int((divergences.get("confidence", pd.Series()) == "high").sum())

    # Default inheritance
    from_default = int(divergences.get("is_from_default", pd.Series(dtype=bool)).sum())

    # Typically env-specific
    env_specific = int(
        divergences.get("typically_env_specific", pd.Series(dtype=bool)).fillna(False).sum()
    )

    return {
        "raw_divergence_count": n,
        "raw_divergence_density": round(density, 4),
        "category_counts": cat_counts,
        "category_densities": {k: round(v, 4) for k, v in cat_densities.items()},
        "high_confidence_count": high_conf,
        "from_default_count": from_default,
        "typically_env_specific_count": env_specific,
        "total_comparable_paths": total_comparable_paths,
    }


def compute_classified_metrics(
    divergences: pd.DataFrame,
    annotations: pd.DataFrame,
    total_comparable_paths: int,
) -> dict[str, Any]:
    """
    Compute evidence-based metrics using manual classification labels.

    Requires annotations joined to divergences.

    Formulas:
    - accidental_density: (accidental count) / total_comparable_paths
    - suspicious_density: (suspicious count) / total_comparable_paths
    - undetermined_proportion: (undetermined count) / total divergences
    - intentional_count: divergences classified as intentional

    Args:
        divergences: DataFrame of divergence records.
        annotations: DataFrame with divergence_id and adjudicated_label columns.
        total_comparable_paths: Denominator for density.

    Returns:
        Dict of classified metric name -> value.
    """
    if divergences.empty or total_comparable_paths == 0:
        return {
            "accidental_count": 0,
            "accidental_density": 0.0,
            "suspicious_count": 0,
            "suspicious_density": 0.0,
            "undetermined_count": 0,
            "undetermined_proportion": 0.0,
            "intentional_count": 0,
            "classified_total": 0,
        }

    # Merge annotations
    if "adjudicated_label" in annotations.columns:
        label_col = "adjudicated_label"
    elif "label" in annotations.columns:
        label_col = "label"
    else:
        logger.warning("No label column found in annotations")
        return {
            "accidental_count": 0,
            "accidental_density": 0.0,
            "suspicious_count": 0,
            "suspicious_density": 0.0,
            "undetermined_count": 0,
            "undetermined_proportion": 0.0,
            "intentional_count": 0,
            "classified_total": 0,
        }

    merged = divergences.merge(
        annotations[["divergence_id", label_col]],
        on="divergence_id",
        how="left",
    )

    label_counts = merged[label_col].value_counts()
    accidental = int(label_counts.get("accidental", 0))
    suspicious = int(label_counts.get("suspicious", 0))
    undetermined = int(label_counts.get("undetermined", 0))
    intentional = int(label_counts.get("intentional", 0))
    classified_total = accidental + suspicious + undetermined + intentional

    return {
        "accidental_count": accidental,
        "accidental_density": round(accidental / total_comparable_paths, 4),
        "suspicious_count": suspicious,
        "suspicious_density": round(suspicious / total_comparable_paths, 4),
        "undetermined_count": undetermined,
        "undetermined_proportion": round(
            undetermined / max(classified_total, 1), 4
        ),
        "intentional_count": intentional,
        "classified_total": classified_total,
    }


def compute_change_metrics(
    current_divergences: pd.DataFrame,
    previous_divergences: pd.DataFrame,
    total_comparable_paths: int,
) -> dict[str, Any]:
    """
    Compute change in divergence between two snapshots.

    Tracks:
    - delta_divergence_count: change in raw count
    - delta_divergence_density: change in density
    - new_divergences: paths divergent now but not before
    - resolved_divergences: paths divergent before but not now
    - persistent_divergences: paths divergent in both

    Args:
        current_divergences: Current snapshot divergences.
        previous_divergences: Previous snapshot divergences.
        total_comparable_paths: Current denominator.

    Returns:
        Dict of change metrics.
    """
    current_paths = set(current_divergences["config_path"]) if not current_divergences.empty else set()
    previous_paths = set(previous_divergences["config_path"]) if not previous_divergences.empty else set()

    new_paths = current_paths - previous_paths
    resolved_paths = previous_paths - current_paths
    persistent_paths = current_paths & previous_paths

    current_count = len(current_divergences)
    previous_count = len(previous_divergences)
    denom = max(total_comparable_paths, 1)

    return {
        "delta_divergence_count": current_count - previous_count,
        "delta_divergence_density": round(
            (current_count - previous_count) / denom, 4
        ),
        "new_divergence_count": len(new_paths),
        "resolved_divergence_count": len(resolved_paths),
        "persistent_divergence_count": len(persistent_paths),
        "new_divergence_paths": sorted(new_paths),
        "resolved_divergence_paths": sorted(resolved_paths),
    }


def summarize_by_category(
    divergences: pd.DataFrame,
) -> pd.DataFrame:
    """
    Produce a summary table of divergence counts and proportions by category.

    Returns:
        DataFrame with columns: category, count, proportion, typically_env_specific.
    """
    if divergences.empty:
        return pd.DataFrame(columns=["category", "count", "proportion", "typically_env_specific"])

    cat_counts = divergences.groupby("category").agg(
        count=("divergence_id", "count"),
        typically_env_specific=("typically_env_specific", "first"),
    ).reset_index()

    cat_counts["proportion"] = round(cat_counts["count"] / cat_counts["count"].sum(), 4)
    return cat_counts.sort_values("count", ascending=False).reset_index(drop=True)


def summarize_by_env_pair(
    divergences: pd.DataFrame,
    total_comparable_paths: int,
) -> pd.DataFrame:
    """
    Produce a summary table of divergence by environment pair.

    Returns:
        DataFrame with columns: env_pair, count, density.
    """
    if divergences.empty:
        return pd.DataFrame(columns=["env_pair", "count", "density"])

    pair_counts = divergences.groupby("env_pair").agg(
        count=("divergence_id", "count"),
    ).reset_index()

    pair_counts["density"] = round(
        pair_counts["count"] / max(total_comparable_paths, 1), 4
    )
    return pair_counts.sort_values("count", ascending=False).reset_index(drop=True)
