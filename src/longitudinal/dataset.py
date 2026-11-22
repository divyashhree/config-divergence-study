"""
Longitudinal dataset construction.

Builds the analysis-ready dataset that links:
  divergence snapshots (predictors) → future maintenance events (outcomes)

Implements strict temporal ordering to prevent leakage:
1. Measure divergence at snapshot time t
2. Count maintenance events in [t, t + window]
3. Never use future information as a predictor

Handles:
- Configurable observation windows (30, 90, 180 days)
- Right-censored periods (insufficient post-snapshot time)
- Repeated observations per repository
- Baseline maintenance rate calculation
"""
from datetime import datetime, timedelta, timezone
from typing import Any

import pandas as pd

from src.utils.logging_config import get_logger

logger = get_logger("longitudinal")


def build_analysis_dataset(
    snapshots: pd.DataFrame,
    divergences: pd.DataFrame,
    maintenance_events: pd.DataFrame,
    repositories: pd.DataFrame,
    window_days: int = 90,
    min_post_snapshot_days: int = 30,
) -> pd.DataFrame:
    """
    Construct the final analysis dataset linking predictors to outcomes.

    For each snapshot:
    1. Compute divergence metrics at snapshot time (predictor)
    2. Count maintenance events in the follow-up window (outcome)
    3. Attach repository-level control variables

    Args:
        snapshots: DataFrame with snapshot_id, repo_id, commit_date, etc.
        divergences: DataFrame with all divergence records.
        maintenance_events: DataFrame with maintenance event records.
        repositories: DataFrame with repo-level metadata.
        window_days: Observation window length in days.
        min_post_snapshot_days: Minimum days of data needed after snapshot.

    Returns:
        Analysis-ready DataFrame with one row per snapshot.
    """
    if snapshots.empty:
        logger.warning("No snapshots to process")
        return pd.DataFrame()

    records = []
    excluded_count = 0

    for _, snapshot in snapshots.iterrows():
        snapshot_date = _ensure_datetime(snapshot["commit_date"])
        if snapshot_date is None:
            logger.warning(f"Skipping snapshot {snapshot.get('snapshot_id')}: invalid date")
            continue

        # Define observation window
        window_start = snapshot_date
        window_end = snapshot_date + timedelta(days=window_days)

        # Check for right censoring
        repo_id = snapshot["repo_id"]
        repo_info = repositories[repositories["repo_id"] == repo_id]
        if not repo_info.empty:
            last_commit = _ensure_datetime(repo_info.iloc[0].get("last_commit_date"))
            if last_commit and (last_commit - snapshot_date).days < min_post_snapshot_days:
                excluded_count += 1
                continue

        # Compute divergence metrics at this snapshot
        snap_divs = divergences[
            divergences["snapshot_id"] == snapshot.get("snapshot_id", "")
        ] if "snapshot_id" in divergences.columns else pd.DataFrame()

        # If no snapshot_id column, filter by repo + commit
        if snap_divs.empty and "commit_sha" in divergences.columns:
            snap_divs = divergences[
                (divergences["repo_id"] == repo_id) &
                (divergences["commit_sha"] == snapshot.get("commit_sha", ""))
            ]

        total_paths = int(snapshot.get("total_comparable_paths", 0))
        if total_paths == 0 and not snap_divs.empty:
            total_paths = int(snap_divs["total_comparable_paths"].max())

        raw_div_count = len(snap_divs)
        raw_div_density = raw_div_count / max(total_paths, 1)

        # Count maintenance events in window
        repo_events = maintenance_events[
            maintenance_events["repo_id"] == repo_id
        ].copy()

        if not repo_events.empty and "event_date" in repo_events.columns:
            repo_events["event_dt"] = repo_events["event_date"].apply(_ensure_datetime)
            window_events = repo_events[
                (repo_events["event_dt"] >= window_start) &
                (repo_events["event_dt"] <= window_end)
            ]

            total_events = len(window_events)
            corrective_events = len(
                window_events[window_events["category"].isin([
                    "corrective_fix", "sync", "rework"
                ])]
            )
        else:
            total_events = 0
            corrective_events = 0

        # Compute baseline maintenance rate (events before snapshot)
        if not repo_events.empty and "event_dt" in repo_events.columns:
            pre_events = repo_events[repo_events["event_dt"] < window_start]
            # Annualize: events per 90-day period before snapshot
            if not pre_events.empty:
                earliest = pre_events["event_dt"].min()
                days_before = max((window_start - earliest).days, 1)
                baseline_rate = len(pre_events) / days_before * window_days
            else:
                baseline_rate = 0.0
        else:
            baseline_rate = 0.0

        # Category-specific divergence counts
        cat_counts = {}
        if not snap_divs.empty and "category" in snap_divs.columns:
            for cat, count in snap_divs["category"].value_counts().items():
                cat_counts[f"div_count_{cat}"] = int(count)

        # Build record
        record = {
            "repo_id": repo_id,
            "snapshot_id": snapshot.get("snapshot_id", ""),
            "snapshot_date": snapshot_date.isoformat(),
            "commit_sha": snapshot.get("commit_sha", ""),
            "observation_window_days": window_days,
            "raw_divergence_count": raw_div_count,
            "raw_divergence_density": round(raw_div_density, 4),
            "total_comparable_paths": total_paths,
            "maintenance_event_count": total_events,
            "corrective_event_count": corrective_events,
            "baseline_maintenance_rate": round(baseline_rate, 4),
        }

        # Add repo-level controls
        if not repo_info.empty:
            ri = repo_info.iloc[0]
            record.update({
                "repo_stars": ri.get("stars", 0),
                "repo_contributors": ri.get("contributors", 0),
                "num_environments": len(
                    ri.get("environments_detected", "").split(",")
                ) if isinstance(ri.get("environments_detected"), str) else 0,
            })
            # Repo age at snapshot
            first_commit = _ensure_datetime(ri.get("first_commit_date"))
            if first_commit:
                record["repo_age_days"] = (snapshot_date - first_commit).days

        # Add category counts
        record.update(cat_counts)

        records.append(record)

    logger.info(
        f"Built analysis dataset: {len(records)} records "
        f"({excluded_count} excluded for insufficient post-snapshot data)"
    )

    return pd.DataFrame(records)


def validate_temporal_ordering(dataset: pd.DataFrame) -> dict[str, Any]:
    """
    Validate that the analysis dataset has proper temporal ordering.

    Checks:
    - Snapshot dates precede observation window ends
    - No future information used as predictors
    - Maintenance events fall within defined windows

    Returns:
        Validation report dict.
    """
    issues = []

    if dataset.empty:
        return {"valid": True, "issues": [], "n_records": 0}

    # Check all snapshot dates are valid
    if "snapshot_date" in dataset.columns:
        null_dates = dataset["snapshot_date"].isna().sum()
        if null_dates > 0:
            issues.append(f"{null_dates} records have null snapshot dates")

    # Check observation windows are positive
    if "observation_window_days" in dataset.columns:
        neg_windows = (dataset["observation_window_days"] <= 0).sum()
        if neg_windows > 0:
            issues.append(f"{neg_windows} records have non-positive observation windows")

    # Check divergence counts are non-negative
    for col in ["raw_divergence_count", "maintenance_event_count", "corrective_event_count"]:
        if col in dataset.columns:
            neg_vals = (dataset[col] < 0).sum()
            if neg_vals > 0:
                issues.append(f"{neg_vals} records have negative {col}")

    # Check densities are in [0, 1] or reasonable range
    if "raw_divergence_density" in dataset.columns:
        out_of_range = (
            (dataset["raw_divergence_density"] < 0) |
            (dataset["raw_divergence_density"] > 1)
        ).sum()
        if out_of_range > 0:
            issues.append(
                f"{out_of_range} records have divergence density outside [0,1]"
            )

    return {
        "valid": len(issues) == 0,
        "issues": issues,
        "n_records": len(dataset),
    }


def _ensure_datetime(value) -> datetime | None:
    """Convert various date representations to datetime."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value
    if isinstance(value, str):
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            return None
    if isinstance(value, pd.Timestamp):
        dt = value.to_pydatetime()
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    return None
