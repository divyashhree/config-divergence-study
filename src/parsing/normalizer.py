"""
YAML configuration normalizer.

Produces canonical representations of YAML configuration trees so that
semantically equivalent configurations compare as equal regardless of:
- Key ordering
- Whitespace and formatting
- Trailing newlines
- Comment differences (comments are stripped by the YAML parser)

Does NOT normalize:
- Value types ("3" vs 3 remain distinct unless configured otherwise)
- Null vs missing keys (these are tracked separately)
- Array ordering (positional semantics preserved)
"""
from typing import Any

import yaml

from src.utils.logging_config import get_logger

logger = get_logger("normalizer")


class YAMLParseError(Exception):
    """Raised when YAML parsing fails."""
    pass


def parse_yaml(content: str, source: str = "<unknown>") -> dict[str, Any]:
    """
    Parse a YAML string into a normalized Python dict.

    Args:
        content: Raw YAML text.
        source: File path or identifier for error messages.

    Returns:
        Parsed dict. Returns empty dict for empty/null documents.

    Raises:
        YAMLParseError: If the content is not valid YAML.
    """
    try:
        result = yaml.safe_load(content)
        if result is None:
            return {}
        if not isinstance(result, dict):
            raise YAMLParseError(
                f"Expected mapping at top level of {source}, got {type(result).__name__}"
            )
        return result
    except yaml.YAMLError as e:
        raise YAMLParseError(f"Failed to parse YAML from {source}: {e}")


def flatten_config(
    tree: dict[str, Any],
    prefix: str = "",
    separator: str = ".",
) -> dict[str, Any]:
    """
    Flatten a nested configuration tree into dot-delimited paths.

    Mappings are joined with '.', lists are indexed with '[n]'.

    Example:
        {"a": {"b": 1}, "c": [10, 20]} ->
        {"a.b": 1, "c[0]": 10, "c[1]": 20}

    Args:
        tree: Nested dict to flatten.
        prefix: Current path prefix (used recursively).
        separator: Path separator for nested keys.

    Returns:
        Flat dict mapping full paths to leaf values.
    """
    flat = {}
    for key, value in tree.items():
        full_key = f"{prefix}{separator}{key}" if prefix else key
        if isinstance(value, dict):
            flat.update(flatten_config(value, full_key, separator))
        elif isinstance(value, list):
            flat.update(_flatten_list(value, full_key, separator))
        else:
            flat[full_key] = value
    return flat


def _flatten_list(
    items: list,
    prefix: str,
    separator: str,
) -> dict[str, Any]:
    """Flatten a list into indexed paths."""
    flat = {}
    for i, item in enumerate(items):
        indexed_key = f"{prefix}[{i}]"
        if isinstance(item, dict):
            flat.update(flatten_config(item, indexed_key, separator))
        elif isinstance(item, list):
            flat.update(_flatten_list(item, indexed_key, separator))
        else:
            flat[indexed_key] = item
    return flat


def normalize_value(value: Any) -> Any:
    """
    Normalize a configuration value for comparison purposes.

    Rules:
    - Strings are stripped of leading/trailing whitespace.
    - None is preserved as None (distinct from missing).
    - Booleans, ints, floats are preserved as-is.
    - Dicts and lists are recursively normalized.
    """
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        return {k: normalize_value(v) for k, v in sorted(value.items())}
    if isinstance(value, list):
        return [normalize_value(item) for item in value]
    return value


def normalize_tree(tree: dict[str, Any]) -> dict[str, Any]:
    """
    Produce a canonical form of a configuration tree.

    - Keys are sorted at every level.
    - Values are normalized.
    - The result is suitable for structural comparison.
    """
    return {k: normalize_value(v) for k, v in sorted(tree.items())}


def compute_comparable_paths(
    config_a: dict[str, Any],
    config_b: dict[str, Any],
) -> set[str]:
    """
    Find all paths that exist in either (or both) flattened configurations.

    This defines the denominator for divergence density calculations.
    """
    flat_a = flatten_config(config_a)
    flat_b = flatten_config(config_b)
    return set(flat_a.keys()) | set(flat_b.keys())


def structural_diff(
    config_a: dict[str, Any],
    config_b: dict[str, Any],
    label_a: str = "env_a",
    label_b: str = "env_b",
) -> list[dict[str, Any]]:
    """
    Compute structural differences between two normalized configurations.

    Returns a list of difference records, each containing:
    - path: The configuration path where the difference occurs.
    - type: 'value_changed', 'key_missing_in_a', 'key_missing_in_b',
            'type_changed', 'null_vs_value'.
    - value_a: Value in config_a (None if key missing).
    - value_b: Value in config_b (None if key missing).

    Does NOT judge whether differences are intentional.
    """
    flat_a = flatten_config(config_a)
    flat_b = flatten_config(config_b)
    all_paths = sorted(set(flat_a.keys()) | set(flat_b.keys()))

    diffs = []
    for path in all_paths:
        in_a = path in flat_a
        in_b = path in flat_b

        if in_a and in_b:
            val_a = flat_a[path]
            val_b = flat_b[path]

            # Normalize for comparison
            norm_a = normalize_value(val_a)
            norm_b = normalize_value(val_b)

            if norm_a == norm_b:
                continue

            # Distinguish type changes from value changes
            if type(norm_a) != type(norm_b):
                # Handle None vs value specially
                if norm_a is None or norm_b is None:
                    diff_type = "null_vs_value"
                else:
                    diff_type = "type_changed"
            else:
                diff_type = "value_changed"

            diffs.append({
                "path": path,
                "type": diff_type,
                "value_a": val_a,
                "value_b": val_b,
                "label_a": label_a,
                "label_b": label_b,
            })
        elif in_a and not in_b:
            diffs.append({
                "path": path,
                "type": "key_missing_in_b",
                "value_a": flat_a[path],
                "value_b": None,
                "label_a": label_a,
                "label_b": label_b,
            })
        else:
            diffs.append({
                "path": path,
                "type": "key_missing_in_a",
                "value_a": None,
                "value_b": flat_b[path],
                "label_a": label_a,
                "label_b": label_b,
            })

    return diffs
