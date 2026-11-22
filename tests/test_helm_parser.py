"""
Tests for the Helm chart parser.

Covers:
- Chart directory discovery
- Environment values file discovery
- Default values parsing
- Deep merge behavior (Helm semantics)
- Override tracking (explicit vs inherited)
- Multi-environment comparison
- Edge cases: missing defaults, single environment, empty values
"""
import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.parsing.helm import (
    deep_merge,
    discover_chart_directories,
    discover_env_values_files,
    parse_helm_chart,
    HelmChart,
)
from src.parsing.normalizer import parse_yaml


FIXTURES_DIR = Path(__file__).parent / "fixtures" / "helm_chart"


# ─────────────────────────────────────────────────────────────────────────────
# deep_merge
# ─────────────────────────────────────────────────────────────────────────────

class TestDeepMerge:
    def test_simple_override(self):
        base = {"a": 1, "b": 2}
        override = {"b": 3}
        result = deep_merge(base, override)
        assert result == {"a": 1, "b": 3}

    def test_nested_merge(self):
        base = {"a": {"b": 1, "c": 2}}
        override = {"a": {"c": 3}}
        result = deep_merge(base, override)
        assert result == {"a": {"b": 1, "c": 3}}

    def test_new_key_added(self):
        base = {"a": 1}
        override = {"b": 2}
        result = deep_merge(base, override)
        assert result == {"a": 1, "b": 2}

    def test_list_replaced_not_merged(self):
        """Helm replaces lists entirely, does not merge elements."""
        base = {"items": [1, 2, 3]}
        override = {"items": [4, 5]}
        result = deep_merge(base, override)
        assert result == {"items": [4, 5]}

    def test_dict_to_scalar_override(self):
        base = {"a": {"b": 1}}
        override = {"a": "scalar"}
        result = deep_merge(base, override)
        assert result == {"a": "scalar"}

    def test_scalar_to_dict_override(self):
        base = {"a": "scalar"}
        override = {"a": {"b": 1}}
        result = deep_merge(base, override)
        assert result == {"a": {"b": 1}}

    def test_base_not_mutated(self):
        base = {"a": {"b": 1}}
        override = {"a": {"c": 2}}
        deep_merge(base, override)
        assert base == {"a": {"b": 1}}

    def test_empty_override(self):
        base = {"a": 1}
        result = deep_merge(base, {})
        assert result == {"a": 1}

    def test_empty_base(self):
        override = {"a": 1}
        result = deep_merge({}, override)
        assert result == {"a": 1}


# ─────────────────────────────────────────────────────────────────────────────
# discover_chart_directories
# ─────────────────────────────────────────────────────────────────────────────

class TestDiscoverChartDirs:
    def test_with_file_list(self):
        file_list = [
            "charts/webapp/Chart.yaml",
            "charts/webapp/values.yaml",
            "charts/api/Chart.yaml",
            "README.md",
        ]
        dirs = discover_chart_directories(Path("/fake"), file_list)
        assert "charts/webapp" in dirs
        assert "charts/api" in dirs
        assert len(dirs) == 2

    def test_root_chart(self):
        file_list = ["Chart.yaml", "values.yaml"]
        dirs = discover_chart_directories(Path("/fake"), file_list)
        assert "" in dirs

    def test_no_charts(self):
        file_list = ["README.md", "Dockerfile"]
        dirs = discover_chart_directories(Path("/fake"), file_list)
        assert len(dirs) == 0


# ─────────────────────────────────────────────────────────────────────────────
# discover_env_values_files
# ─────────────────────────────────────────────────────────────────────────────

class TestDiscoverEnvFiles:
    def test_standard_naming(self):
        files = [
            "charts/app/Chart.yaml",
            "charts/app/values.yaml",
            "charts/app/values-dev.yaml",
            "charts/app/values-prod.yaml",
        ]
        result = discover_env_values_files(files, "charts/app")
        assert "development" in result
        assert result["development"] == "charts/app/values-dev.yaml"
        assert "production" in result
        assert result["production"] == "charts/app/values-prod.yaml"

    def test_dot_naming(self):
        files = [
            "Chart.yaml",
            "values.yaml",
            "values.staging.yaml",
        ]
        result = discover_env_values_files(files, "")
        assert "staging" in result

    def test_directory_based(self):
        files = [
            "chart/Chart.yaml",
            "chart/values.yaml",
            "chart/environments/production/values.yaml",
            "chart/environments/staging/values.yaml",
        ]
        result = discover_env_values_files(files, "chart")
        assert "production" in result
        assert "staging" in result

    def test_no_env_files(self):
        files = ["Chart.yaml", "values.yaml"]
        result = discover_env_values_files(files, "")
        assert len(result) == 0


# ─────────────────────────────────────────────────────────────────────────────
# parse_helm_chart (using fixtures)
# ─────────────────────────────────────────────────────────────────────────────

class TestParseHelmChart:
    @pytest.fixture
    def fixture_files(self):
        """List files in the test fixture chart directory."""
        return [
            "Chart.yaml",
            "values.yaml",
            "values-dev.yaml",
            "values-prod.yaml",
        ]

    @pytest.fixture
    def file_reader(self):
        """File reader that reads from fixtures directory."""
        def reader(path: str) -> str:
            return (FIXTURES_DIR / path).read_text(encoding="utf-8")
        return reader

    def test_basic_parse(self, fixture_files, file_reader):
        chart = parse_helm_chart(
            repo_path=FIXTURES_DIR,
            chart_dir="",
            file_list=fixture_files,
            file_reader=file_reader,
            redact_secrets=False,
        )
        assert chart is not None
        assert chart.name == "sample-webapp"
        assert "development" in chart.environments
        assert "production" in chart.environments

    def test_effective_config_merges_defaults(self, fixture_files, file_reader):
        chart = parse_helm_chart(
            repo_path=FIXTURES_DIR,
            chart_dir="",
            file_list=fixture_files,
            file_reader=file_reader,
            redact_secrets=False,
        )
        # Dev doesn't set autoscaling — should inherit from defaults
        dev_effective = chart.get_effective_config("development")
        assert "autoscaling" in dev_effective
        assert dev_effective["autoscaling"]["enabled"] is False

        # Prod explicitly sets autoscaling
        prod_effective = chart.get_effective_config("production")
        assert prod_effective["autoscaling"]["enabled"] is True
        assert prod_effective["autoscaling"]["maxReplicas"] == 10

    def test_override_tracking(self, fixture_files, file_reader):
        chart = parse_helm_chart(
            repo_path=FIXTURES_DIR,
            chart_dir="",
            file_list=fixture_files,
            file_reader=file_reader,
            redact_secrets=False,
        )
        tracking = chart.get_override_tracking("development")

        # replicaCount explicitly set in dev values
        assert tracking["replicaCount"]["source"] == "explicit_override"
        assert tracking["replicaCount"]["value"] == 1

        # autoscaling.enabled NOT set in dev — inherited from defaults
        assert tracking["autoscaling.enabled"]["source"] == "inherited_default"
        assert tracking["autoscaling.enabled"]["is_from_default"] is True

    def test_environments_differ(self, fixture_files, file_reader):
        chart = parse_helm_chart(
            repo_path=FIXTURES_DIR,
            chart_dir="",
            file_list=fixture_files,
            file_reader=file_reader,
            redact_secrets=False,
        )
        dev = chart.get_effective_config("development")
        prod = chart.get_effective_config("production")

        # Replicas should differ
        assert dev["replicaCount"] != prod["replicaCount"]

        # Resources should differ
        assert dev["resources"]["limits"]["cpu"] != prod["resources"]["limits"]["cpu"]

    def test_secret_redaction(self, fixture_files, file_reader):
        chart = parse_helm_chart(
            repo_path=FIXTURES_DIR,
            chart_dir="",
            file_list=fixture_files,
            file_reader=file_reader,
            redact_secrets=True,
        )
        # serviceAccount.name should not be redacted (not a secret pattern)
        prod = chart.env_values["production"]
        assert prod.get("serviceAccount", {}).get("name") != "[REDACTED]"
