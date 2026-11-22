"""
Secret detection and redaction for configuration values.

Prevents credentials, tokens, passwords, and private keys from appearing
in the divergence dataset, logs, or dashboard.
"""
import re
from typing import Any

from src.utils.logging_config import get_logger

logger = get_logger("secrets")

# Default patterns that indicate a value is sensitive
DEFAULT_SENSITIVE_KEY_PATTERNS = [
    r"password",
    r"secret",
    r"token",
    r"apikey",
    r"api[_-]?key",
    r"credential",
    r"private[_-]?key",
    r"auth",
    r"connection[_-]?string",
    r"access[_-]?key",
    r"client[_-]?secret",
    r"signing[_-]?key",
]

# Value patterns that look like secrets (base64, hex strings, etc.)
SENSITIVE_VALUE_PATTERNS = [
    # Long hex strings (>= 32 chars)
    re.compile(r"^[0-9a-fA-F]{32,}$"),
    # Base64-encoded strings (>= 20 chars)
    re.compile(r"^[A-Za-z0-9+/]{20,}={0,2}$"),
    # AWS-style keys
    re.compile(r"^AKIA[0-9A-Z]{16}$"),
]

REDACTED = "[REDACTED]"


def is_sensitive_key(key: str, patterns: list[str] | None = None) -> bool:
    """
    Check whether a configuration key name suggests it holds a secret.

    Args:
        key: The configuration key or path segment.
        patterns: Custom patterns. Defaults to DEFAULT_SENSITIVE_KEY_PATTERNS.

    Returns:
        True if the key matches a sensitive pattern.
    """
    if patterns is None:
        patterns = DEFAULT_SENSITIVE_KEY_PATTERNS
    key_lower = key.lower()
    for pat in patterns:
        if re.search(pat, key_lower):
            return True
    return False


def is_sensitive_value(value: Any) -> bool:
    """
    Check whether a value looks like it could be a secret based on its format.

    This is a heuristic — it catches common patterns but is not exhaustive.
    """
    if not isinstance(value, str):
        return False
    if len(value) < 16:
        return False
    for pattern in SENSITIVE_VALUE_PATTERNS:
        if pattern.match(value):
            return True
    return False


def redact_value(value: Any, key: str = "", patterns: list[str] | None = None) -> Any:
    """
    Redact a value if its key or content suggests it is sensitive.

    Args:
        value: The configuration value.
        key: The key name or full path.
        patterns: Custom key patterns.

    Returns:
        REDACTED string if sensitive, original value otherwise.
    """
    if is_sensitive_key(key, patterns):
        return REDACTED
    if is_sensitive_value(value):
        return REDACTED
    return value


def redact_config_tree(
    tree: dict[str, Any],
    parent_path: str = "",
    patterns: list[str] | None = None,
) -> dict[str, Any]:
    """
    Recursively redact sensitive values in a configuration tree.

    Returns a new dict with secrets replaced by REDACTED.
    """
    result = {}
    for key, value in tree.items():
        full_path = f"{parent_path}.{key}" if parent_path else key
        if isinstance(value, dict):
            result[key] = redact_config_tree(value, full_path, patterns)
        elif isinstance(value, list):
            result[key] = [
                redact_config_tree(item, f"{full_path}[{i}]", patterns)
                if isinstance(item, dict)
                else redact_value(item, full_path, patterns)
                for i, item in enumerate(value)
            ]
        else:
            result[key] = redact_value(value, full_path, patterns)
    return result
