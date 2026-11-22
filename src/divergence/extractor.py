"""
Divergence extractor — the core analysis engine.

Takes parsed Helm charts and produces structured divergence records
by comparing environment-specific configurations.

Each record documents:
- What differs (path, values)
- Where it was found (repo, files, environments)
- What category it belongs to (taxonomy)
- Whether defaults were involved (provenance)
- Confidence and limitations

Does NOT determine intent (intentional vs accidental).
"""
import uuid
from datetime import datetime, timezone
from typing import Any

from src.parsing.helm import HelmChart
from src.parsing.normalizer import structural_diff, flatten_config, compute_comparable_paths
from src.divergence.taxonomy import classify_path, is_typically_env_specific
from src.utils.secrets import redact_value
from src.utils.logging_config import get_logger

logger = get_logger("extractor")


def extract_divergences(
    chart: HelmChart,
    repo_id: str,
    commit_sha: str,
    commit_date: str | None = None,
    compare_effective: bool = True,
    redact: bool = True,
) -> list[dict[str, Any]]:
    """
    Extract all divergence records from a parsed Helm chart.

    Compares every pair of environments. If compare_effective is True,
    compares effective (merged with defaults) configurations. Otherwise
    compares raw environment values files only.

    Args:
        chart: Parsed HelmChart with environment values.
        repo_id: Repository identifier (e.g., 'owner/repo').
        commit_sha: Git commit SHA for this snapshot.
        commit_date: ISO timestamp of the commit.
        compare_effective: Whether to merge with chart defaults before comparing.
        redact: Whether to redact sensitive values.

    Returns:
        List of divergence record dicts.
    """
    divergences = []
    envs = chart.environments

    if len(envs) < 2 and not chart.default_values:
        logger.warning(f"Chart {chart.name}: insufficient environments for comparison")
        return divergences

    # Generate all environment pairs
    env_pairs = []
    for i, env_a in enumerate(envs):
        for env_b in envs[i + 1:]:
            env_pairs.append((env_a, env_b))

    # If only one environment, compare against defaults
    if len(envs) == 1 and chart.default_values:
        env_pairs.append(("_defaults", envs[0]))

    for env_a, env_b in env_pairs:
        pair_divergences = _compare_environment_pair(
            chart=chart,
            env_a=env_a,
            env_b=env_b,
            repo_id=repo_id,
            commit_sha=commit_sha,
            commit_date=commit_date,
            compare_effective=compare_effective,
            redact=redact,
        )
        divergences.extend(pair_divergences)

    logger.info(
        f"Chart '{chart.name}': extracted {len(divergences)} divergences "
        f"across {len(env_pairs)} environment pairs"
    )
    return divergences


def _compare_environment_pair(
    chart: HelmChart,
    env_a: str,
    env_b: str,
    repo_id: str,
    commit_sha: str,
    commit_date: str | None,
    compare_effective: bool,
    redact: bool,
) -> list[dict[str, Any]]:
    """Compare two environments and produce divergence records."""

    # Get configurations to compare
    if env_a == "_defaults":
        config_a = chart.default_values
        file_a = f"{chart.chart_path}/values.yaml" if chart.chart_path else "values.yaml"
        label_a = "defaults"
    else:
        config_a = (
            chart.get_effective_config(env_a) if compare_effective
            else chart.env_values[env_a]
        )
        file_a = chart.env_file_map.get(env_a, "")
        label_a = env_a

    config_b = (
        chart.get_effective_config(env_b) if compare_effective
        else chart.env_values[env_b]
    )
    file_b = chart.env_file_map.get(env_b, "")
    label_b = env_b

    # Get override tracking for provenance
    tracking_a = None
    tracking_b = None
    if compare_effective and env_a != "_defaults":
        try:
            tracking_a = chart.get_override_tracking(env_a)
        except Exception as e:
            logger.debug(f"Override tracking failed for {env_a}: {e}")
    if compare_effective:
        try:
            tracking_b = chart.get_override_tracking(env_b)
        except Exception as e:
            logger.debug(f"Override tracking failed for {env_b}: {e}")

    # Compute structural differences
    diffs = structural_diff(config_a, config_b, label_a, label_b)

    # Count comparable paths for density calculation
    comparable = compute_comparable_paths(config_a, config_b)

    divergences = []
    for diff in diffs:
        path = diff["path"]

        # Determine provenance (default vs explicit)
        is_from_default = False
        default_value = None
        if tracking_a and path in tracking_a:
            if tracking_a[path]["is_from_default"]:
                is_from_default = True
                default_value = tracking_a[path]["default_value"]
        if tracking_b and path in tracking_b:
            if tracking_b[path]["is_from_default"]:
                is_from_default = True
                if default_value is None:
                    default_value = tracking_b[path]["default_value"]

        # Classify by taxonomy
        category = classify_path(path)

        # Determine confidence
        confidence = _assess_confidence(diff, is_from_default, category)

        # Redact sensitive values
        val_a = diff["value_a"]
        val_b = diff["value_b"]
        was_redacted = False
        if redact:
            val_a_redacted = redact_value(val_a, path)
            val_b_redacted = redact_value(val_b, path)
            if val_a_redacted != val_a or val_b_redacted != val_b:
                was_redacted = True
            val_a = val_a_redacted
            val_b = val_b_redacted
            if default_value is not None:
                default_value = redact_value(default_value, path)

        divergence_record = {
            "divergence_id": str(uuid.uuid4()),
            "repo_id": repo_id,
            "commit_sha": commit_sha,
            "commit_date": commit_date,
            "env_pair": f"{label_a}::{label_b}",
            "config_path": path,
            "diff_type": diff["type"],
            "category": category,
            "value_env_a": _safe_str(val_a),
            "value_env_b": _safe_str(val_b),
            "source_file_a": file_a,
            "source_file_b": file_b,
            "is_from_default": is_from_default,
            "default_value": _safe_str(default_value),
            "confidence": confidence,
            "typically_env_specific": is_typically_env_specific(category),
            "total_comparable_paths": len(comparable),
            "evidence_notes": _build_evidence_notes(diff, is_from_default, category),
            "redacted": was_redacted,
        }

        divergences.append(divergence_record)

    return divergences


def _assess_confidence(
    diff: dict[str, Any],
    is_from_default: bool,
    category: str,
) -> str:
    """
    Assess confidence in the divergence observation.

    High: Clear structural difference between explicit values.
    Medium: Difference involves default inheritance.
    Low: Complex structure or array comparison with uncertain matching.
    """
    if diff["type"] in ("key_missing_in_a", "key_missing_in_b"):
        if is_from_default:
            return "medium"
        return "high"

    if is_from_default:
        return "medium"

    # Array elements may have uncertain positional matching
    if "[" in diff["path"]:
        return "medium"

    return "high"


def _build_evidence_notes(
    diff: dict[str, Any],
    is_from_default: bool,
    category: str,
) -> str:
    """Generate human-readable evidence notes for a divergence."""
    notes = []

    if diff["type"] == "key_missing_in_a":
        notes.append(f"Key present in {diff['label_b']} but not in {diff['label_a']}")
    elif diff["type"] == "key_missing_in_b":
        notes.append(f"Key present in {diff['label_a']} but not in {diff['label_b']}")
    elif diff["type"] == "type_changed":
        notes.append(f"Type mismatch: {type(diff['value_a']).__name__} vs {type(diff['value_b']).__name__}")
    elif diff["type"] == "null_vs_value":
        notes.append("One environment has null/None where the other has a value")
    else:
        notes.append("Value differs between environments")

    if is_from_default:
        notes.append("At least one value is inherited from chart defaults (not explicitly set)")

    env_specific = is_typically_env_specific(category)
    if env_specific is True:
        notes.append(f"Category '{category}' typically varies by environment (may be intentional)")
    elif env_specific is False:
        notes.append(f"Category '{category}' is typically consistent across environments (warrants attention)")

    return "; ".join(notes)


def _safe_str(value: Any) -> str | None:
    """Convert a value to string for storage, handling None."""
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        import json
        return json.dumps(value, default=str, sort_keys=True)
    return str(value)


def compute_snapshot_summary(
    divergences: list[dict[str, Any]],
) -> dict[str, Any]:
    """
    Compute summary statistics for a set of divergence records.

    Returns a dict suitable for the snapshots table.
    """
    if not divergences:
        return {
            "total_divergences": 0,
            "total_comparable_paths": 0,
            "raw_divergence_density": 0.0,
            "by_category": {},
            "by_env_pair": {},
            "high_confidence_count": 0,
            "from_default_count": 0,
        }

    # Use the first record's comparable paths (same for all in a snapshot)
    total_paths = max(d.get("total_comparable_paths", 1) for d in divergences)

    by_category = {}
    by_env_pair = {}
    high_conf = 0
    from_default = 0

    for d in divergences:
        cat = d.get("category", "unknown")
        by_category[cat] = by_category.get(cat, 0) + 1

        pair = d.get("env_pair", "unknown")
        by_env_pair[pair] = by_env_pair.get(pair, 0) + 1

        if d.get("confidence") == "high":
            high_conf += 1
        if d.get("is_from_default"):
            from_default += 1

    return {
        "total_divergences": len(divergences),
        "total_comparable_paths": total_paths,
        "raw_divergence_density": len(divergences) / max(total_paths, 1),
        "by_category": by_category,
        "by_env_pair": by_env_pair,
        "high_confidence_count": high_conf,
        "from_default_count": from_default,
    }
