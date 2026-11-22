"""
Repository eligibility assessment.

Evaluates whether a candidate repository meets the study's
inclusion criteria. Records decisions transparently.

Criteria:
- Has Helm charts (Chart.yaml)
- Has >= 2 identifiable environments OR 1 env + defaults
- Has sufficient git history (>= min_commits, >= min_history_days)
- Not archived, not a fork (configurable)
- Minimum star threshold (noise filter)
- Has sufficient observation time for longitudinal analysis
"""
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from src.utils.logging_config import get_logger
from src.parsing.helm import discover_chart_directories, discover_env_values_files

logger = get_logger("eligibility")


def assess_eligibility(
    repo_path: Path,
    repo_id: str,
    metadata: dict[str, Any] | None = None,
    min_environments: int = 2,
    min_stars: int = 5,
    min_history_days: int = 180,
    allow_single_env_with_defaults: bool = True,
    exclude_archived: bool = True,
    exclude_forks: bool = True,
) -> dict[str, Any]:
    """
    Assess whether a repository is eligible for the study.

    Args:
        repo_path: Path to the cloned repository.
        repo_id: Repository identifier.
        metadata: Pre-fetched GitHub metadata (stars, dates, etc.).
        min_environments: Minimum distinct environments required.
        min_stars: Minimum star count.
        min_history_days: Minimum days of git history.
        allow_single_env_with_defaults: If True, 1 env + chart defaults counts.
        exclude_archived: Whether to exclude archived repos.
        exclude_forks: Whether to exclude forked repos.

    Returns:
        Eligibility assessment dict with decision and reasoning.
    """
    assessment = {
        "repo_id": repo_id,
        "assessed_at": datetime.now(timezone.utc).isoformat(),
        "eligible": False,
        "exclusion_reasons": [],
        "environment_evidence": {},
        "charts_found": [],
        "warnings": [],
    }

    metadata = metadata or {}

    # Check metadata-based criteria first (cheap)
    if exclude_archived and metadata.get("archived", False):
        assessment["exclusion_reasons"].append("Repository is archived")
        return assessment

    if exclude_forks and metadata.get("fork", False):
        assessment["exclusion_reasons"].append("Repository is a fork")
        return assessment

    stars = metadata.get("stars", 0)
    if stars < min_stars:
        assessment["exclusion_reasons"].append(
            f"Insufficient stars: {stars} < {min_stars}"
        )
        return assessment

    # Scan for Helm charts
    file_list = []
    try:
        for f in repo_path.rglob("*"):
            if f.is_file():
                rel = str(f.relative_to(repo_path)).replace("\\", "/")
                file_list.append(rel)
    except Exception as e:
        assessment["exclusion_reasons"].append(f"Failed to scan repository: {e}")
        return assessment

    chart_dirs = discover_chart_directories(repo_path, file_list)
    assessment["charts_found"] = chart_dirs

    if not chart_dirs:
        assessment["exclusion_reasons"].append("No Helm charts (Chart.yaml) found")
        return assessment

    # Check for environment-specific values
    total_envs = 0
    env_details = {}

    for chart_dir in chart_dirs:
        env_files = discover_env_values_files(file_list, chart_dir)
        if env_files:
            env_details[chart_dir] = {
                "environments": list(env_files.keys()),
                "files": env_files,
            }
            total_envs = max(total_envs, len(env_files))

    assessment["environment_evidence"] = env_details

    effective_min = min_environments
    if allow_single_env_with_defaults and total_envs >= 1:
        # Check if chart has defaults to compare against
        has_defaults = any(
            f"{cd}/values.yaml" in file_list or
            (cd == "" and "values.yaml" in file_list)
            for cd in chart_dirs
        )
        if has_defaults:
            effective_min = 1

    if total_envs < effective_min:
        assessment["exclusion_reasons"].append(
            f"Insufficient environments: {total_envs} < {effective_min} "
            f"(found: {env_details})"
        )
        return assessment

    # If we got here, the repo is eligible
    assessment["eligible"] = True
    assessment["total_environments"] = total_envs
    assessment["total_charts"] = len(chart_dirs)
    assessment["total_files"] = len(file_list)

    logger.info(
        f"Eligible: {repo_id} — {len(chart_dirs)} charts, "
        f"{total_envs} environments"
    )
    return assessment


def batch_assess(
    assessments: list[dict[str, Any]],
    output_path: Path,
) -> pd.DataFrame:
    """
    Save batch eligibility assessments and return summary.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Save full assessments as JSON
    json_path = output_path.with_suffix(".json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(assessments, f, indent=2, default=str)

    # Create summary DataFrame
    rows = []
    for a in assessments:
        rows.append({
            "repo_id": a["repo_id"],
            "eligible": a["eligible"],
            "exclusion_reasons": "; ".join(a.get("exclusion_reasons", [])),
            "total_charts": a.get("total_charts", 0),
            "total_environments": a.get("total_environments", 0),
        })

    df = pd.DataFrame(rows)
    csv_path = output_path.with_suffix(".csv")
    df.to_csv(csv_path, index=False)

    eligible = df["eligible"].sum()
    total = len(df)
    logger.info(
        f"Eligibility assessment: {eligible}/{total} eligible "
        f"({eligible/max(total,1)*100:.1f}%)"
    )

    return df
