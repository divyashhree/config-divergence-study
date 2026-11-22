"""
Maintenance event mining from git history.

Identifies and categorizes configuration-related maintenance events:
- Commits modifying configuration files
- Keyword analysis for corrective vs routine changes
- Event categorization
- Deduplication by time proximity

Does NOT treat every configuration change as a defect correction.
"""
import re
from datetime import datetime, timedelta, timezone
from typing import Any

import pandas as pd

from src.utils.logging_config import get_logger
from src.utils.git_ops import get_commit_log, get_changed_files

logger = get_logger("events")


# Default config file patterns that indicate configuration changes
CONFIG_FILE_PATTERNS = [
    r"values.*\.ya?ml$",
    r"Chart\.ya?ml$",
    r"kustomization\.ya?ml$",
    r".*\.ya?ml$",  # Broad — will be filtered by directory context
]

# Keywords suggesting corrective maintenance
CORRECTIVE_KEYWORDS = [
    "fix", "bug", "hotfix", "patch", "correct", "revert", "rollback",
    "sync", "align", "mismatch", "wrong", "missing", "typo", "broken",
    "issue", "error", "fail", "resolve",
]

# Keywords suggesting routine/non-corrective changes
ROUTINE_KEYWORDS = [
    "update", "upgrade", "bump", "version", "release", "deploy",
    "add", "feature", "enhance", "improve", "refactor", "clean",
]

# Keywords that suggest the change is unrelated to configuration maintenance
EXCLUDE_KEYWORDS = [
    "readme", "changelog", "license", "docs", "documentation",
    "ci", "test", "lint", "format", "style",
]


def extract_maintenance_events(
    repo_path,
    repo_id: str,
    since: str | None = None,
    until: str | None = None,
    config_paths: list[str] | None = None,
    max_commits: int = 1000,
) -> list[dict[str, Any]]:
    """
    Extract configuration-related maintenance events from git history.

    Args:
        repo_path: Path to the cloned repository.
        repo_id: Repository identifier.
        since: ISO date string for start of period.
        until: ISO date string for end of period.
        config_paths: Specific paths to monitor. If None, uses broad YAML patterns.
        max_commits: Maximum commits to process.

    Returns:
        List of maintenance event dicts.
    """
    from pathlib import Path
    repo_path = Path(repo_path)

    # Get commits touching YAML files
    yaml_globs = config_paths or ["*.yaml", "*.yml"]
    commits = get_commit_log(
        repo_path,
        max_count=max_commits,
        since=since,
        until=until,
        paths=yaml_globs,
    )

    logger.info(f"Found {len(commits)} commits touching config files")

    events = []
    for commit in commits:
        # Get files changed in this commit
        changed_files = get_changed_files(repo_path, commit["sha"])

        # Filter to config-relevant files
        config_files = [
            f for f in changed_files
            if _is_config_file(f)
        ]

        if not config_files:
            continue

        # Categorize the event
        category = _categorize_event(commit["message"], config_files)

        event = {
            "event_id": f"{repo_id}:{commit['sha'][:12]}",
            "repo_id": repo_id,
            "event_type": "commit",
            "source_id": commit["sha"],
            "event_date": commit["date"],
            "author": commit["author"],
            "category": category,
            "config_files_changed": config_files,
            "title": commit["message"],
            "description": "",  # Would need git show for full body
            "validation_status": "auto",
            "linked_events": [],
            "episode_id": None,  # Set during deduplication
        }
        events.append(event)

    logger.info(
        f"Extracted {len(events)} config-related events "
        f"({_count_by_category(events)})"
    )
    return events


def _is_config_file(filepath: str) -> bool:
    """Check if a file path looks like a configuration file."""
    lower = filepath.lower()
    # Must be YAML
    if not (lower.endswith(".yaml") or lower.endswith(".yml")):
        return False
    # Exclude test fixtures, documentation, CI config
    exclude_dirs = ["test", "tests", "spec", "docs", "doc", ".github", ".circleci"]
    parts = filepath.replace("\\", "/").split("/")
    for part in parts:
        if part.lower() in exclude_dirs:
            return False
    return True


def _categorize_event(message: str, config_files: list[str]) -> str:
    """
    Categorize a maintenance event based on commit message and files.

    Categories:
    - corrective_fix: Bug fix, error correction
    - sync: Synchronizing configuration across environments
    - rework: Reverting or redoing configuration
    - resource_tune: Adjusting resource limits/replicas
    - routine: Routine update, version bump, feature addition
    - unrelated: Changes that happened to touch config files
    """
    msg_lower = message.lower()

    # Check for exclusion first
    for kw in EXCLUDE_KEYWORDS:
        if kw in msg_lower and not any(ck in msg_lower for ck in CORRECTIVE_KEYWORDS):
            return "unrelated"

    # Corrective patterns
    if any(kw in msg_lower for kw in ["revert", "rollback"]):
        return "rework"

    if any(kw in msg_lower for kw in ["sync", "align", "mismatch", "consistent"]):
        return "sync"

    if any(kw in msg_lower for kw in ["fix", "bug", "hotfix", "patch", "correct",
                                       "wrong", "missing", "typo", "broken",
                                       "issue", "error", "fail"]):
        return "corrective_fix"

    # Resource tuning
    if any(kw in msg_lower for kw in ["resource", "replica", "memory", "cpu",
                                       "limit", "request", "scale", "hpa"]):
        return "resource_tune"

    # Routine changes
    if any(kw in msg_lower for kw in ROUTINE_KEYWORDS):
        return "routine"

    # Default: check if files suggest config maintenance
    values_files = [f for f in config_files if "values" in f.lower()]
    if values_files:
        return "routine"

    return "unrelated"


def deduplicate_events(
    events: list[dict[str, Any]],
    time_window_hours: int = 4,
) -> list[dict[str, Any]]:
    """
    Group related events into logical maintenance episodes.

    Events by the same author within time_window_hours touching
    similar files are grouped into episodes.

    Args:
        events: List of event dicts with event_date, author, config_files_changed.
        time_window_hours: Maximum gap between related events.

    Returns:
        Events with episode_id assigned.
    """
    if not events:
        return events

    # Sort by date
    sorted_events = sorted(events, key=lambda e: e["event_date"])

    episode_counter = 0
    for i, event in enumerate(sorted_events):
        if event["episode_id"] is not None:
            continue

        episode_counter += 1
        episode_id = f"episode_{episode_counter}"
        event["episode_id"] = episode_id

        # Look for related subsequent events
        event_date = _parse_date(event["event_date"])
        if event_date is None:
            continue

        for j in range(i + 1, len(sorted_events)):
            other = sorted_events[j]
            if other["episode_id"] is not None:
                continue

            other_date = _parse_date(other["event_date"])
            if other_date is None:
                continue

            # Check time proximity
            if (other_date - event_date).total_seconds() > time_window_hours * 3600:
                break

            # Check same author
            if other["author"] != event["author"]:
                continue

            # Check file overlap
            files_a = set(event["config_files_changed"])
            files_b = set(other["config_files_changed"])
            if files_a & files_b:
                other["episode_id"] = episode_id
                other["linked_events"] = other.get("linked_events", []) + [event["source_id"]]
                event["linked_events"] = event.get("linked_events", []) + [other["source_id"]]

    return sorted_events


def _parse_date(date_str: str) -> datetime | None:
    """Parse an ISO date string."""
    try:
        return datetime.fromisoformat(date_str.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


def _count_by_category(events: list[dict]) -> str:
    """Count events by category for logging."""
    counts = {}
    for e in events:
        cat = e.get("category", "unknown")
        counts[cat] = counts.get(cat, 0) + 1
    return ", ".join(f"{k}: {v}" for k, v in sorted(counts.items()))


def events_to_dataframe(events: list[dict[str, Any]]) -> pd.DataFrame:
    """Convert events list to a DataFrame, exploding list fields."""
    if not events:
        return pd.DataFrame()

    df = pd.DataFrame(events)
    # Convert list fields to strings for CSV storage
    if "config_files_changed" in df.columns:
        df["config_files_changed"] = df["config_files_changed"].apply(
            lambda x: "|".join(x) if isinstance(x, list) else str(x)
        )
    if "linked_events" in df.columns:
        df["linked_events"] = df["linked_events"].apply(
            lambda x: "|".join(x) if isinstance(x, list) else str(x)
        )
    return df
