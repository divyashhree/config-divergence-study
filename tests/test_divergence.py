"""
Tests for the divergence extractor and taxonomy.

Covers:
- Taxonomy path classification
- Divergence extraction from parsed charts
- Provenance tracking (default vs explicit)
- Confidence assessment
- Evidence notes generation
- Snapshot summary computation
- Category distribution correctness
"""
import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.divergence.taxonomy import (
    classify_path,
    is_typically_env_specific,
    get_all_categories,
)
from src.divergence.extractor import (
    extract_divergences,
    compute_snapshot_summary,
)
from src.parsing.helm import parse_helm_chart


FIXTURES_DIR = Path(__file__).parent / "fixtures" / "helm_chart"


# ─────────────────────────────────────────────────────────────────────────────
# Taxonomy classification
# ─────────────────────────────────────────────────────────────────────────────

class TestTaxonomy:
    def test_replica_count(self):
        assert classify_path("replicaCount") == "replica_scaling"

    def test_nested_replicas(self):
        assert classify_path("deployment.replicaCount") == "replica_scaling"

    def test_autoscaling(self):
        assert classify_path("autoscaling.maxReplicas") == "replica_scaling"

    def test_resource_limits(self):
        assert classify_path("resources.limits.cpu") == "resource_limits"

    def test_nested_resources(self):
        assert classify_path("app.resources.requests.memory") == "resource_limits"

    def test_image_tag(self):
        assert classify_path("image.tag") == "image_version"

    def test_probe(self):
        assert classify_path("livenessProbe.initialDelaySeconds") == "health_check"

    def test_env_var(self):
        assert classify_path("env[0].value") == "env_variable"

    def test_security_context(self):
        assert classify_path("securityContext.runAsNonRoot") == "security"

    def test_service_port(self):
        assert classify_path("service.port") == "networking"

    def test_ingress_enabled(self):
        """ingress.enabled should classify as feature_flag, not networking."""
        assert classify_path("ingress.enabled") == "feature_flag"

    def test_ingress_hosts(self):
        """ingress.hosts should classify as networking."""
        assert classify_path("ingress.hosts[0].host") == "networking"

    def test_persistence(self):
        assert classify_path("persistence.size") == "persistence"

    def test_unknown(self):
        assert classify_path("completely.random.path") == "unknown"

    def test_typically_env_specific(self):
        assert is_typically_env_specific("replica_scaling") is True
        assert is_typically_env_specific("resource_limits") is True
        assert is_typically_env_specific("health_check") is False
        assert is_typically_env_specific("security") is False

    def test_all_categories(self):
        cats = get_all_categories()
        assert "replica_scaling" in cats
        assert "unknown" in cats


# ─────────────────────────────────────────────────────────────────────────────
# Divergence extraction
# ─────────────────────────────────────────────────────────────────────────────

class TestExtractor:
    @pytest.fixture
    def chart(self):
        file_list = [
            "Chart.yaml",
            "values.yaml",
            "values-dev.yaml",
            "values-prod.yaml",
        ]
        def reader(path: str) -> str:
            return (FIXTURES_DIR / path).read_text(encoding="utf-8")

        return parse_helm_chart(
            repo_path=FIXTURES_DIR,
            chart_dir="",
            file_list=file_list,
            file_reader=reader,
            redact_secrets=False,
        )

    def test_divergences_found(self, chart):
        divs = extract_divergences(
            chart, repo_id="test/repo", commit_sha="abc123",
        )
        assert len(divs) > 0

    def test_divergence_structure(self, chart):
        divs = extract_divergences(
            chart, repo_id="test/repo", commit_sha="abc123",
        )
        # Check required fields
        required_fields = [
            "divergence_id", "repo_id", "commit_sha", "env_pair",
            "config_path", "diff_type", "category", "value_env_a",
            "value_env_b", "is_from_default", "confidence",
            "evidence_notes",
        ]
        for field in required_fields:
            assert field in divs[0], f"Missing field: {field}"

    def test_env_pair_format(self, chart):
        divs = extract_divergences(
            chart, repo_id="test/repo", commit_sha="abc123",
        )
        env_pairs = set(d["env_pair"] for d in divs)
        assert "development::production" in env_pairs

    def test_categories_assigned(self, chart):
        divs = extract_divergences(
            chart, repo_id="test/repo", commit_sha="abc123",
        )
        categories = set(d["category"] for d in divs)
        # We expect several categories from our fixtures
        assert len(categories) > 1
        # Replica count differs between dev and prod
        replica_divs = [d for d in divs if d["category"] == "replica_scaling"]
        assert len(replica_divs) > 0

    def test_resource_divergences(self, chart):
        divs = extract_divergences(
            chart, repo_id="test/repo", commit_sha="abc123",
        )
        resource_divs = [d for d in divs if d["category"] == "resource_limits"]
        assert len(resource_divs) > 0

    def test_provenance_tracking(self, chart):
        divs = extract_divergences(
            chart, repo_id="test/repo", commit_sha="abc123",
        )
        # Some divergences should involve defaults
        from_defaults = [d for d in divs if d["is_from_default"]]
        # autoscaling differs — dev inherits from defaults, prod overrides
        assert len(from_defaults) > 0

    def test_snapshot_summary(self, chart):
        divs = extract_divergences(
            chart, repo_id="test/repo", commit_sha="abc123",
        )
        summary = compute_snapshot_summary(divs)
        assert summary["total_divergences"] == len(divs)
        assert summary["total_comparable_paths"] > 0
        assert summary["raw_divergence_density"] > 0
        assert len(summary["by_category"]) > 0

    def test_confidence_values(self, chart):
        divs = extract_divergences(
            chart, repo_id="test/repo", commit_sha="abc123",
        )
        valid_confidences = {"high", "medium", "low"}
        for d in divs:
            assert d["confidence"] in valid_confidences

    def test_unique_ids(self, chart):
        divs = extract_divergences(
            chart, repo_id="test/repo", commit_sha="abc123",
        )
        ids = [d["divergence_id"] for d in divs]
        assert len(ids) == len(set(ids)), "Divergence IDs must be unique"
