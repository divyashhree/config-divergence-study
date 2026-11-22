"""
Tests for the YAML normalizer.

Covers:
- Valid YAML parsing
- Invalid YAML handling
- Empty documents
- Non-dict top-level documents
- Key ordering normalization
- Flattening nested structures
- Array indexing
- Value normalization (strings, booleans, nulls)
- Structural diff: value changes, missing keys, type changes, null vs value
"""
import pytest
import sys
from pathlib import Path

# Ensure src is importable
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.parsing.normalizer import (
    parse_yaml,
    flatten_config,
    normalize_value,
    normalize_tree,
    structural_diff,
    compute_comparable_paths,
    YAMLParseError,
)


# ─────────────────────────────────────────────────────────────────────────────
# parse_yaml
# ─────────────────────────────────────────────────────────────────────────────

class TestParseYaml:
    def test_simple_dict(self):
        result = parse_yaml("a: 1\nb: 2")
        assert result == {"a": 1, "b": 2}

    def test_nested_dict(self):
        result = parse_yaml("a:\n  b:\n    c: 3")
        assert result == {"a": {"b": {"c": 3}}}

    def test_empty_document(self):
        result = parse_yaml("")
        assert result == {}

    def test_null_document(self):
        result = parse_yaml("---\n")
        assert result == {}

    def test_explicit_null(self):
        """Explicit null should be preserved, not converted to missing."""
        result = parse_yaml("a: null\nb: ~\nc: 3")
        assert result == {"a": None, "b": None, "c": 3}

    def test_invalid_yaml(self):
        with pytest.raises(YAMLParseError):
            parse_yaml("a: [unclosed bracket")

    def test_non_dict_toplevel(self):
        with pytest.raises(YAMLParseError, match="Expected mapping"):
            parse_yaml("- item1\n- item2")

    def test_boolean_values(self):
        result = parse_yaml("a: true\nb: false\nc: yes\nd: no")
        assert result["a"] is True
        assert result["b"] is False
        # PyYAML 6.x: 'yes' and 'no' remain strings in safe_load
        # This behavior depends on YAML version

    def test_numeric_types(self):
        result = parse_yaml('a: 42\nb: 3.14\nc: "42"')
        assert isinstance(result["a"], int)
        assert isinstance(result["b"], float)
        assert isinstance(result["c"], str)


# ─────────────────────────────────────────────────────────────────────────────
# flatten_config
# ─────────────────────────────────────────────────────────────────────────────

class TestFlattenConfig:
    def test_simple(self):
        result = flatten_config({"a": 1, "b": 2})
        assert result == {"a": 1, "b": 2}

    def test_nested(self):
        result = flatten_config({"a": {"b": {"c": 3}}})
        assert result == {"a.b.c": 3}

    def test_array(self):
        result = flatten_config({"items": [10, 20, 30]})
        assert result == {"items[0]": 10, "items[1]": 20, "items[2]": 30}

    def test_array_of_dicts(self):
        result = flatten_config({
            "env": [
                {"name": "A", "value": "1"},
                {"name": "B", "value": "2"},
            ]
        })
        assert result == {
            "env[0].name": "A",
            "env[0].value": "1",
            "env[1].name": "B",
            "env[1].value": "2",
        }

    def test_mixed_nesting(self):
        result = flatten_config({
            "a": {
                "b": [
                    {"c": 1},
                    {"c": 2},
                ],
            },
        })
        assert result == {
            "a.b[0].c": 1,
            "a.b[1].c": 2,
        }

    def test_empty_dict(self):
        result = flatten_config({})
        assert result == {}

    def test_null_values(self):
        result = flatten_config({"a": None, "b": 1})
        assert result == {"a": None, "b": 1}


# ─────────────────────────────────────────────────────────────────────────────
# normalize_value
# ─────────────────────────────────────────────────────────────────────────────

class TestNormalizeValue:
    def test_string_strip(self):
        assert normalize_value("  hello  ") == "hello"

    def test_none_preserved(self):
        assert normalize_value(None) is None

    def test_bool_preserved(self):
        assert normalize_value(True) is True
        assert normalize_value(False) is False

    def test_int_preserved(self):
        assert normalize_value(42) == 42

    def test_dict_sorted(self):
        result = normalize_value({"z": 1, "a": 2})
        assert list(result.keys()) == ["a", "z"]

    def test_list_preserved_order(self):
        result = normalize_value([3, 1, 2])
        assert result == [3, 1, 2]  # Order preserved!


# ─────────────────────────────────────────────────────────────────────────────
# structural_diff
# ─────────────────────────────────────────────────────────────────────────────

class TestStructuralDiff:
    def test_identical(self):
        config = {"a": 1, "b": "hello"}
        diffs = structural_diff(config, config)
        assert len(diffs) == 0

    def test_value_changed(self):
        a = {"a": 1, "b": 2}
        b = {"a": 1, "b": 3}
        diffs = structural_diff(a, b)
        assert len(diffs) == 1
        assert diffs[0]["path"] == "b"
        assert diffs[0]["type"] == "value_changed"
        assert diffs[0]["value_a"] == 2
        assert diffs[0]["value_b"] == 3

    def test_key_missing_in_b(self):
        a = {"a": 1, "b": 2}
        b = {"a": 1}
        diffs = structural_diff(a, b)
        assert len(diffs) == 1
        assert diffs[0]["type"] == "key_missing_in_b"
        assert diffs[0]["path"] == "b"

    def test_key_missing_in_a(self):
        a = {"a": 1}
        b = {"a": 1, "b": 2}
        diffs = structural_diff(a, b)
        assert len(diffs) == 1
        assert diffs[0]["type"] == "key_missing_in_a"

    def test_type_changed(self):
        a = {"a": "42"}
        b = {"a": 42}
        diffs = structural_diff(a, b)
        assert len(diffs) == 1
        assert diffs[0]["type"] == "type_changed"

    def test_null_vs_value(self):
        a = {"a": None}
        b = {"a": 1}
        diffs = structural_diff(a, b)
        assert len(diffs) == 1
        assert diffs[0]["type"] == "null_vs_value"

    def test_nested_diff(self):
        a = {"top": {"nested": {"deep": 1}}}
        b = {"top": {"nested": {"deep": 2}}}
        diffs = structural_diff(a, b)
        assert len(diffs) == 1
        assert diffs[0]["path"] == "top.nested.deep"

    def test_key_order_invariant(self):
        """Different key ordering should not produce differences."""
        a = {"z": 1, "a": 2}
        b = {"a": 2, "z": 1}
        diffs = structural_diff(a, b)
        assert len(diffs) == 0

    def test_whitespace_normalization(self):
        """Whitespace in string values should be normalized."""
        a = {"msg": "  hello  "}
        b = {"msg": "hello"}
        diffs = structural_diff(a, b)
        assert len(diffs) == 0

    def test_labels_in_output(self):
        a = {"a": 1}
        b = {"a": 2}
        diffs = structural_diff(a, b, label_a="dev", label_b="prod")
        assert diffs[0]["label_a"] == "dev"
        assert diffs[0]["label_b"] == "prod"

    def test_comparable_paths(self):
        a = {"a": 1, "b": 2}
        b = {"b": 3, "c": 4}
        paths = compute_comparable_paths(a, b)
        assert paths == {"a", "b", "c"}


# ─────────────────────────────────────────────────────────────────────────────
# normalize_tree
# ─────────────────────────────────────────────────────────────────────────────

class TestNormalizeTree:
    def test_keys_sorted(self):
        tree = {"z": 1, "a": {"z": 3, "a": 4}}
        result = normalize_tree(tree)
        assert list(result.keys()) == ["a", "z"]
        assert list(result["a"].keys()) == ["a", "z"]

    def test_idempotent(self):
        tree = {"b": 1, "a": 2}
        result1 = normalize_tree(tree)
        result2 = normalize_tree(result1)
        assert result1 == result2
