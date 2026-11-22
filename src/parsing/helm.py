"""
Helm chart values parser.

Handles:
- Chart.yaml metadata extraction
- Default values.yaml parsing
- Environment-specific values file discovery
- Values merging (env values override defaults)
- Tracking which values are explicitly set vs inherited from defaults
"""
import re
from pathlib import Path
from typing import Any

import yaml

from src.parsing.normalizer import parse_yaml, flatten_config, normalize_tree, YAMLParseError
from src.utils.logging_config import get_logger
from src.utils.secrets import redact_config_tree

logger = get_logger("helm")


class HelmChart:
    """
    Represents a parsed Helm chart with its default values
    and environment-specific overrides.
    """

    def __init__(
        self,
        chart_path: str,
        chart_meta: dict[str, Any],
        default_values: dict[str, Any],
        env_values: dict[str, dict[str, Any]],
        env_file_map: dict[str, str],
        parse_warnings: list[str],
    ):
        self.chart_path = chart_path
        self.chart_meta = chart_meta
        self.default_values = default_values
        self.env_values = env_values  # {env_name: parsed_values}
        self.env_file_map = env_file_map  # {env_name: file_path}
        self.parse_warnings = parse_warnings

    @property
    def name(self) -> str:
        return self.chart_meta.get("name", "unknown")

    @property
    def environments(self) -> list[str]:
        return sorted(self.env_values.keys())

    def get_effective_config(self, env_name: str) -> dict[str, Any]:
        """
        Compute the effective configuration for an environment.

        Helm merges values in this order (later overrides earlier):
        1. Chart defaults (values.yaml)
        2. Environment-specific values file

        This is a simplified model — real Helm also merges:
        - Parent chart values
        - --set flags
        - Multiple -f flags
        We document this limitation and track it.

        Returns:
            Merged configuration dict.
        """
        if env_name not in self.env_values:
            raise ValueError(f"Unknown environment: {env_name}")

        # Deep merge: defaults first, then env-specific overrides
        merged = deep_merge(self.default_values, self.env_values[env_name])
        return merged

    def get_override_tracking(self, env_name: str) -> dict[str, dict[str, Any]]:
        """
        For each path in the effective config, track whether the value
        came from defaults or was explicitly overridden.

        Returns:
            Dict mapping config paths to {value, source, default_value}.
        """
        if env_name not in self.env_values:
            raise ValueError(f"Unknown environment: {env_name}")

        flat_defaults = flatten_config(self.default_values)
        flat_env = flatten_config(self.env_values[env_name])
        effective = flatten_config(self.get_effective_config(env_name))

        tracking = {}
        for path, value in effective.items():
            if path in flat_env:
                source = "explicit_override"
                default_val = flat_defaults.get(path)
            elif path in flat_defaults:
                source = "inherited_default"
                default_val = flat_defaults[path]
            else:
                source = "unknown"
                default_val = None

            tracking[path] = {
                "value": value,
                "source": source,
                "default_value": default_val,
                "is_from_default": source == "inherited_default",
            }

        return tracking


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """
    Deep merge two dicts. Override values take precedence.
    Nested dicts are merged recursively. Non-dict values are replaced.

    This mirrors Helm's values merging behavior for nested maps.
    Lists are NOT merged — override replaces the entire list,
    consistent with Helm semantics.
    """
    result = dict(base)
    for key, value in override.items():
        if (
            key in result
            and isinstance(result[key], dict)
            and isinstance(value, dict)
        ):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def discover_chart_directories(
    repo_path: Path,
    file_list: list[str] | None = None,
) -> list[str]:
    """
    Find directories containing Helm charts (identified by Chart.yaml).

    Args:
        repo_path: Root of the repository.
        file_list: Pre-computed list of files (from git ls-tree).
                   If None, scans the filesystem.

    Returns:
        List of chart directory paths relative to repo root.
    """
    chart_dirs = []

    if file_list is not None:
        for f in file_list:
            if f.endswith("Chart.yaml") or f.endswith("Chart.yml"):
                chart_dir = str(Path(f).parent).replace("\\", "/")
                if chart_dir == ".":
                    chart_dir = ""
                chart_dirs.append(chart_dir)
    else:
        for chart_file in repo_path.rglob("Chart.yaml"):
            rel = chart_file.parent.relative_to(repo_path)
            chart_dirs.append(str(rel))
        for chart_file in repo_path.rglob("Chart.yml"):
            rel = chart_file.parent.relative_to(repo_path)
            chart_dirs.append(str(rel))

    # Deduplicate and sort
    return sorted(set(chart_dirs))


def discover_env_values_files(
    file_list: list[str],
    chart_dir: str,
    env_patterns: dict[str, list[str]] | None = None,
) -> dict[str, str]:
    """
    Discover environment-specific values files for a chart.

    Searches for files matching patterns like:
    - values-prod.yaml, values-dev.yaml
    - values.prod.yaml, values.dev.yaml
    - envs/prod/values.yaml, environments/prod/values.yaml

    Args:
        file_list: All files in the repository.
        chart_dir: Path to the chart directory.
        env_patterns: Mapping of canonical env names to name variants.

    Returns:
        Dict mapping environment names to file paths.
    """
    if env_patterns is None:
        env_patterns = {
            "production": ["prod", "production", "prd"],
            "staging": ["staging", "stg", "stage", "preprod", "pre-prod"],
            "development": ["dev", "development", "local"],
            "testing": ["test", "testing", "qa", "uat"],
        }

    discovered = {}

    # Normalize chart_dir for path matching
    chart_prefix = chart_dir.rstrip("/") + "/" if chart_dir else ""

    for env_name, variants in env_patterns.items():
        for variant in variants:
            # Pattern 1: values-{env}.yaml in chart dir or nearby
            candidates = [
                f"{chart_prefix}values-{variant}.yaml",
                f"{chart_prefix}values-{variant}.yml",
                f"{chart_prefix}values.{variant}.yaml",
                f"{chart_prefix}values.{variant}.yml",
                # Pattern 2: environment subdirectory
                f"{chart_prefix}{variant}/values.yaml",
                f"{chart_prefix}{variant}/values.yml",
                f"{chart_prefix}environments/{variant}/values.yaml",
                f"{chart_prefix}envs/{variant}/values.yaml",
                f"{chart_prefix}deploy/{variant}/values.yaml",
            ]

            # Also search parent/sibling directories for multi-chart repos
            if chart_dir:
                parent = str(Path(chart_dir).parent)
                if parent != ".":
                    candidates.extend([
                        f"{parent}/values-{variant}.yaml",
                        f"{parent}/values-{variant}.yml",
                        f"{parent}/{variant}/values.yaml",
                        f"{parent}/environments/{variant}/values.yaml",
                    ])

            for candidate in candidates:
                if candidate in file_list:
                    discovered[env_name] = candidate
                    break
            if env_name in discovered:
                break

    return discovered


def parse_helm_chart(
    repo_path: Path,
    chart_dir: str,
    file_list: list[str],
    env_patterns: dict[str, list[str]] | None = None,
    file_reader=None,
    redact_secrets: bool = True,
) -> HelmChart | None:
    """
    Parse a Helm chart with its default and environment-specific values.

    Args:
        repo_path: Repository root path.
        chart_dir: Chart directory relative to repo root.
        file_list: All files in the repository.
        env_patterns: Environment name patterns.
        file_reader: Callable(file_path) -> str for reading files.
                     Defaults to reading from filesystem.
        redact_secrets: Whether to redact sensitive values.

    Returns:
        HelmChart object, or None if parsing fails entirely.
    """
    warnings = []

    if file_reader is None:
        def file_reader(path: str) -> str:
            full_path = repo_path / path
            return full_path.read_text(encoding="utf-8", errors="replace")

    chart_prefix = chart_dir.rstrip("/") + "/" if chart_dir else ""

    # 1. Parse Chart.yaml
    chart_meta = {}
    chart_yaml_path = f"{chart_prefix}Chart.yaml"
    try:
        chart_content = file_reader(chart_yaml_path)
        chart_meta = parse_yaml(chart_content, chart_yaml_path)
    except (YAMLParseError, FileNotFoundError, OSError) as e:
        warnings.append(f"Failed to parse Chart.yaml: {e}")
        logger.warning(f"Chart.yaml parse error at {chart_yaml_path}: {e}")

    # 2. Parse default values.yaml
    default_values = {}
    defaults_path = f"{chart_prefix}values.yaml"
    try:
        defaults_content = file_reader(defaults_path)
        default_values = parse_yaml(defaults_content, defaults_path)
    except (YAMLParseError, FileNotFoundError, OSError) as e:
        warnings.append(f"Failed to parse default values.yaml: {e}")
        logger.warning(f"Default values parse error at {defaults_path}: {e}")

    # 3. Discover and parse environment values
    env_file_map = discover_env_values_files(file_list, chart_dir, env_patterns)
    env_values = {}

    for env_name, env_file in env_file_map.items():
        try:
            content = file_reader(env_file)
            parsed = parse_yaml(content, env_file)
            env_values[env_name] = parsed
            logger.info(f"Parsed {env_name} values from {env_file}")
        except (YAMLParseError, FileNotFoundError, OSError) as e:
            warnings.append(f"Failed to parse {env_name} values ({env_file}): {e}")
            logger.warning(f"Env values parse error: {env_file}: {e}")

    if not env_values:
        logger.info(f"No environment-specific values found for chart at {chart_dir}")
        return None

    if len(env_values) < 2 and not default_values:
        warnings.append("Only one environment found and no defaults — limited comparison possible")

    # 4. Apply secret redaction
    if redact_secrets:
        default_values = redact_config_tree(default_values)
        env_values = {
            env: redact_config_tree(vals)
            for env, vals in env_values.items()
        }

    chart = HelmChart(
        chart_path=chart_dir,
        chart_meta=chart_meta,
        default_values=default_values,
        env_values=env_values,
        env_file_map=env_file_map,
        parse_warnings=warnings,
    )

    logger.info(
        f"Parsed chart '{chart.name}' at {chart_dir}: "
        f"{len(env_values)} environments ({', '.join(chart.environments)}), "
        f"{len(warnings)} warnings"
    )
    return chart
