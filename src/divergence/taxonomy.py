"""
Divergence taxonomy — classifies configuration differences by category.

The taxonomy labels the *type* of difference, NOT whether it is intentional
or accidental. Intent classification is a separate step (see classification/).

Categories are matched against the configuration path using glob-like patterns.
"""
import fnmatch
from typing import Any

from src.utils.logging_config import get_logger

logger = get_logger("taxonomy")


# ─────────────────────────────────────────────────────────────────────────────
# Default taxonomy definition
# ─────────────────────────────────────────────────────────────────────────────

DEFAULT_TAXONOMY: dict[str, dict[str, Any]] = {
    "replica_scaling": {
        "patterns": [
            "replicaCount", "replicas",
            "autoscaling.*", "hpa.*",
            "*.replicaCount", "*.replicas",
            "*.autoscaling.*", "*.hpa.*",
            "*minReplicas*", "*maxReplicas*",
        ],
        "description": "Replica count and autoscaling configuration",
        "typically_env_specific": True,
        "rationale": "Production typically runs more replicas than dev/staging",
    },
    "resource_limits": {
        "patterns": [
            "resources.*", "*.resources.*",
            "*requests.cpu*", "*requests.memory*",
            "*limits.cpu*", "*limits.memory*",
        ],
        "description": "CPU and memory requests/limits",
        "typically_env_specific": True,
        "rationale": "Resource allocation typically varies by environment",
    },
    "image_version": {
        "patterns": [
            "image.*", "*.image.*",
            "*imageTag*", "*imageRepository*",
            "*.tag", "*.repository",
        ],
        "description": "Container image repository, tag, or pull policy",
        "typically_env_specific": True,
        "rationale": "Environments may deploy different versions",
    },
    "health_check": {
        "patterns": [
            "*Probe*", "*probe*",
            "livenessProbe.*", "readinessProbe.*", "startupProbe.*",
            "*.livenessProbe.*", "*.readinessProbe.*", "*.startupProbe.*",
        ],
        "description": "Health check and probe configuration",
        "typically_env_specific": False,
        "rationale": "Usually should be consistent; differences may indicate issues",
    },
    "env_variable": {
        "patterns": [
            "env", "env.*", "env[*",
            "envFrom.*", "extraEnv.*", "extraEnvVars.*",
            "*.env", "*.env.*", "*.env[*",
            "*.extraEnv.*", "*.extraEnvVars.*",
        ],
        "description": "Environment variables and config injection",
        "typically_env_specific": True,
        "rationale": "Env vars often contain environment-specific endpoints/settings",
    },
    "security": {
        "patterns": [
            "*security*", "*tls*", "*ssl*",
            "*rbac*", "*serviceAccount*",
            "*networkPolicy*", "*podSecurityPolicy*",
            "*securityContext*",
        ],
        "description": "Security, TLS, RBAC, network policy",
        "typically_env_specific": False,
        "rationale": "Security config should generally be consistent",
    },
    "networking": {
        "patterns": [
            "service.*", "service",
            "ingress.hosts*", "ingress.tls*", "ingress.className*",
            "ingress.annotations*", "ingress.ingressClassName*",
            "*port*", "*host*", "*domain*",
            "*.service.*", "*.ingress.hosts*", "*.ingress.tls*",
        ],
        "description": "Service, ingress, and networking configuration",
        "typically_env_specific": True,
        "rationale": "Hosts and domains are environment-specific by nature",
    },
    "feature_flag": {
        "patterns": [
            "*.enabled", "enabled",
            "*.enable", "enable",
        ],
        "description": "Feature toggles and component enablement",
        "typically_env_specific": True,
        "rationale": "Some features may be selectively enabled per environment",
    },
    "persistence": {
        "patterns": [
            "persistence.*", "*storage*",
            "*pvc*", "*volume*",
            "*.persistence.*",
        ],
        "description": "Storage and persistence configuration",
        "typically_env_specific": True,
        "rationale": "Storage classes and sizes often differ by environment",
    },
}


def classify_path(
    path: str,
    taxonomy: dict[str, dict[str, Any]] | None = None,
) -> str:
    """
    Classify a configuration path into a taxonomy category.

    Uses glob-style pattern matching against the path.
    Returns the first matching category, or 'unknown'.

    Args:
        path: Dot-delimited configuration path (e.g., 'resources.limits.cpu').
        taxonomy: Custom taxonomy dict. Uses DEFAULT_TAXONOMY if None.

    Returns:
        Category name string.
    """
    if taxonomy is None:
        taxonomy = DEFAULT_TAXONOMY

    for category, definition in taxonomy.items():
        for pattern in definition.get("patterns", []):
            if _match_config_path(path, pattern):
                return category

    return "unknown"


def _match_config_path(path: str, pattern: str) -> bool:
    """
    Match a configuration path against a glob-like pattern.

    Supports * for single-segment wildcards and handles
    array indices in paths.
    """
    # Remove array indices for pattern matching
    clean_path = _strip_array_indices(path)
    clean_pattern = _strip_array_indices(pattern)

    # Try exact fnmatch
    if fnmatch.fnmatch(clean_path, clean_pattern):
        return True

    # Also try matching individual path segments
    if fnmatch.fnmatch(clean_path.lower(), clean_pattern.lower()):
        return True

    return False


def _strip_array_indices(path: str) -> str:
    """Remove array index notation from a path for pattern matching."""
    import re
    return re.sub(r'\[\d+\]', '', path)


def get_category_info(
    category: str,
    taxonomy: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Get metadata about a taxonomy category."""
    if taxonomy is None:
        taxonomy = DEFAULT_TAXONOMY
    return taxonomy.get(category, {
        "description": "Unknown category",
        "typically_env_specific": None,
        "rationale": "No matching taxonomy entry",
    })


def is_typically_env_specific(
    category: str,
    taxonomy: dict[str, dict[str, Any]] | None = None,
) -> bool | None:
    """
    Whether differences in this category are typically intentional
    environment-specific variation.

    Returns:
        True if typically intentional, False if potentially suspicious,
        None if unknown.
    """
    info = get_category_info(category, taxonomy)
    return info.get("typically_env_specific")


def get_all_categories(
    taxonomy: dict[str, dict[str, Any]] | None = None,
) -> list[str]:
    """List all category names including 'unknown'."""
    if taxonomy is None:
        taxonomy = DEFAULT_TAXONOMY
    return sorted(taxonomy.keys()) + ["unknown"]
