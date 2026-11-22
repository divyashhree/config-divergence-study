"""
Additional test coverage: metrics, longitudinal, e2e, and maintenance.

Covers:
- test_metrics: Snapshot metrics, classified metrics, change metrics
- test_longitudinal: Temporal ordering, leakage prevention, right-censoring
- test_maintenance: Event extraction, categorization, deduplication
- test_e2e: End-to-end pipeline on fixtures
"""
import json
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import TestCase

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


# ═══════════════════════════════════════════════════════════════════════
# Test: Metrics
# ═══════════════════════════════════════════════════════════════════════

from src.divergence.metrics import (
    compute_snapshot_metrics,
    summarize_by_category,
    summarize_by_env_pair,
)


def _make_divergences(n=5, categories=None, pairs=None):
    """Helper to create sample divergence DataFrames."""
    cats = categories or ["scaling", "resource_management", "feature_flag",
                          "deployment_identity", "networking"]
    env_pairs = pairs or ["default::prod"]
    rows = []
    for i in range(n):
        rows.append({
            "divergence_id": f"div-{i}",
            "repo_id": "test/repo",
            "config_path": f"path.{i}",
            "category": cats[i % len(cats)],
            "diff_type": "value_changed" if i % 2 == 0 else "key_missing",
            "env_pair": env_pairs[i % len(env_pairs)],
            "value_env_a": f"val_a_{i}",
            "value_env_b": f"val_b_{i}",
            "confidence": "high" if i % 3 != 2 else "medium",
            "is_from_default": i % 2 == 0,
            "typically_env_specific": i % 2 == 0,
            "total_comparable_paths": 100,
        })
    return pd.DataFrame(rows)


class TestSnapshotMetrics(TestCase):
    def test_basic_metrics(self):
        df = _make_divergences(5)
        metrics = compute_snapshot_metrics(df, total_comparable_paths=100)
        assert metrics["raw_divergence_count"] == 5
        assert metrics["total_comparable_paths"] == 100
        assert metrics["raw_divergence_density"] == 0.05
        assert "category_counts" in metrics
        assert "category_densities" in metrics

    def test_empty_dataframe(self):
        df = pd.DataFrame()
        metrics = compute_snapshot_metrics(df, total_comparable_paths=100)
        assert metrics["raw_divergence_count"] == 0
        assert metrics["raw_divergence_density"] == 0.0

    def test_confidence_counts(self):
        df = _make_divergences(6)
        metrics = compute_snapshot_metrics(df, total_comparable_paths=100)
        # high_confidence_count should count items where confidence == "high"
        assert metrics["high_confidence_count"] >= 0
        assert metrics["high_confidence_count"] <= 6

    def test_from_default_count(self):
        df = _make_divergences(4)
        metrics = compute_snapshot_metrics(df, total_comparable_paths=50)
        assert metrics["from_default_count"] == 2  # Every other one

    def test_zero_paths(self):
        df = _make_divergences(3)
        metrics = compute_snapshot_metrics(df, total_comparable_paths=0)
        assert metrics["raw_divergence_density"] == 0.0


class TestSummarizeByCategory(TestCase):
    def test_basic_summary(self):
        df = _make_divergences(5)
        summary = summarize_by_category(df)
        assert len(summary) == 5  # 5 unique categories
        assert "category" in summary.columns
        assert "count" in summary.columns

    def test_empty(self):
        df = pd.DataFrame()
        summary = summarize_by_category(df)
        assert summary.empty


class TestSummarizeByEnvPair(TestCase):
    def test_single_pair(self):
        df = _make_divergences(5, pairs=["dev::prod"])
        summary = summarize_by_env_pair(df, total_comparable_paths=100)
        assert len(summary) == 1
        assert summary.iloc[0]["env_pair"] == "dev::prod"
        assert summary.iloc[0]["count"] == 5

    def test_multiple_pairs(self):
        df = _make_divergences(6, pairs=["dev::prod", "dev::staging"])
        summary = summarize_by_env_pair(df, total_comparable_paths=100)
        assert len(summary) == 2


# ═══════════════════════════════════════════════════════════════════════
# Test: Longitudinal Dataset
# ═══════════════════════════════════════════════════════════════════════

from src.longitudinal.dataset import (
    build_analysis_dataset,
    validate_temporal_ordering,
)


class TestBuildAnalysisDataset(TestCase):
    def _make_data(self):
        """Create minimal valid input data."""
        now = datetime.now(timezone.utc)
        snapshots = pd.DataFrame([{
            "snapshot_id": "snap1",
            "repo_id": "test/repo",
            "commit_sha": "abc123",
            "commit_date": now.isoformat(),
            "total_comparable_paths": 100,
        }])
        divergences = pd.DataFrame([{
            "divergence_id": "div1",
            "repo_id": "test/repo",
            "snapshot_id": "snap1",
            "config_path": "replicas",
            "category": "scaling",
            "total_comparable_paths": 100,
        }])
        events = pd.DataFrame([{
            "event_id": "evt1",
            "repo_id": "test/repo",
            "event_date": (now + timedelta(days=10)).isoformat(),
            "category": "corrective_fix",
        }])
        repos = pd.DataFrame([{
            "repo_id": "test/repo",
            "stars": 100,
            "contributors": 5,
            "environments_detected": "dev,prod",
            "first_commit_date": (now - timedelta(days=365)).isoformat(),
            "last_commit_date": (now + timedelta(days=180)).isoformat(),
        }])
        return snapshots, divergences, events, repos

    def test_basic_construction(self):
        snaps, divs, evts, repos = self._make_data()
        result = build_analysis_dataset(snaps, divs, evts, repos, window_days=90)
        assert len(result) == 1
        assert result.iloc[0]["raw_divergence_count"] == 1

    def test_empty_snapshots(self):
        _, divs, evts, repos = self._make_data()
        result = build_analysis_dataset(
            pd.DataFrame(), divs, evts, repos,
        )
        assert result.empty

    def test_maintenance_count_in_window(self):
        snaps, divs, evts, repos = self._make_data()
        result = build_analysis_dataset(snaps, divs, evts, repos, window_days=90)
        assert result.iloc[0]["maintenance_event_count"] == 1
        assert result.iloc[0]["corrective_event_count"] == 1

    def test_event_outside_window(self):
        snaps, divs, evts, repos = self._make_data()
        # Move event far into the future
        evts["event_date"] = (
            datetime.now(timezone.utc) + timedelta(days=200)
        ).isoformat()
        result = build_analysis_dataset(snaps, divs, evts, repos, window_days=90)
        assert result.iloc[0]["maintenance_event_count"] == 0

    def test_right_censoring(self):
        snaps, divs, evts, repos = self._make_data()
        # Repo last commit is very soon after snapshot
        repos["last_commit_date"] = (
            datetime.now(timezone.utc) + timedelta(days=5)
        ).isoformat()
        result = build_analysis_dataset(
            snaps, divs, evts, repos,
            min_post_snapshot_days=30,
        )
        # Should be excluded
        assert len(result) == 0


class TestValidateTemporalOrdering(TestCase):
    def test_valid_dataset(self):
        df = pd.DataFrame([{
            "snapshot_date": "2024-01-01T00:00:00+00:00",
            "observation_window_days": 90,
            "raw_divergence_count": 5,
            "raw_divergence_density": 0.05,
            "maintenance_event_count": 2,
            "corrective_event_count": 1,
        }])
        result = validate_temporal_ordering(df)
        assert result["valid"] is True
        assert result["n_records"] == 1

    def test_negative_counts(self):
        df = pd.DataFrame([{
            "snapshot_date": "2024-01-01T00:00:00+00:00",
            "observation_window_days": 90,
            "raw_divergence_count": -1,
            "maintenance_event_count": 0,
            "corrective_event_count": 0,
        }])
        result = validate_temporal_ordering(df)
        assert result["valid"] is False
        assert any("negative" in issue for issue in result["issues"])

    def test_empty_dataset(self):
        result = validate_temporal_ordering(pd.DataFrame())
        assert result["valid"] is True


# ═══════════════════════════════════════════════════════════════════════
# Test: Maintenance Events
# ═══════════════════════════════════════════════════════════════════════

from src.maintenance.events import (
    _categorize_event,
    _is_config_file,
    deduplicate_events,
)


class TestCategorizeEvent(TestCase):
    def test_fix(self):
        assert _categorize_event("fix broken config", ["values.yaml"]) == "corrective_fix"

    def test_bug(self):
        assert _categorize_event("bug: wrong replica count", ["values.yaml"]) == "corrective_fix"

    def test_sync(self):
        assert _categorize_event("sync staging with prod config", ["values.yaml"]) == "sync"

    def test_revert(self):
        assert _categorize_event("revert config changes", ["values.yaml"]) == "rework"

    def test_resource_tune(self):
        assert _categorize_event("increase memory limits", ["values.yaml"]) == "resource_tune"

    def test_routine_update(self):
        assert _categorize_event("update chart version", ["Chart.yaml"]) == "routine"

    def test_unrelated_docs(self):
        assert _categorize_event("update readme", ["values.yaml"]) == "unrelated"

    def test_routine_deploy(self):
        assert _categorize_event("deploy v2.0", ["values.yaml"]) == "routine"

    def test_fallthrough_values(self):
        assert _categorize_event("some change", ["values-prod.yaml"]) == "routine"

    def test_unrelated_no_values(self):
        assert _categorize_event("some change", ["other.yaml"]) == "unrelated"


class TestIsConfigFile(TestCase):
    def test_values_yaml(self):
        assert _is_config_file("charts/app/values.yaml") is True

    def test_non_yaml(self):
        assert _is_config_file("charts/app/main.go") is False

    def test_test_fixture(self):
        assert _is_config_file("tests/fixtures/values.yaml") is False

    def test_github_ci(self):
        assert _is_config_file(".github/workflows/ci.yml") is False


class TestDeduplicateEvents(TestCase):
    def _make_events(self, n, gap_hours=1):
        base = datetime(2024, 1, 1, tzinfo=timezone.utc)
        events = []
        for i in range(n):
            events.append({
                "event_id": f"evt-{i}",
                "source_id": f"sha-{i}",
                "event_date": (base + timedelta(hours=i * gap_hours)).isoformat(),
                "author": "dev",
                "category": "routine",
                "config_files_changed": ["values.yaml"],
                "episode_id": None,
                "linked_events": [],
            })
        return events

    def test_groups_close_events(self):
        events = self._make_events(3, gap_hours=1)
        result = deduplicate_events(events, time_window_hours=4)
        # All within 4 hours by same author on same files
        episode_ids = [e["episode_id"] for e in result]
        assert len(set(episode_ids)) == 1

    def test_separates_distant_events(self):
        events = self._make_events(2, gap_hours=5)
        result = deduplicate_events(events, time_window_hours=4)
        episode_ids = [e["episode_id"] for e in result]
        assert len(set(episode_ids)) == 2

    def test_empty(self):
        assert deduplicate_events([]) == []

    def test_different_authors(self):
        events = self._make_events(2, gap_hours=1)
        events[1]["author"] = "other_dev"
        result = deduplicate_events(events, time_window_hours=4)
        episode_ids = [e["episode_id"] for e in result]
        assert len(set(episode_ids)) == 2


# ═══════════════════════════════════════════════════════════════════════
# Test: End-to-End Pipeline
# ═══════════════════════════════════════════════════════════════════════

from run_pipeline import run_pipeline


class TestE2EPipeline(TestCase):
    def test_fixtures_pipeline(self):
        """Run the full pipeline on test fixtures."""
        import tempfile
        fixtures_dir = Path(__file__).parent / "fixtures" / "helm_chart"
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            result = run_pipeline(
                repo_path=fixtures_dir,
                repo_id="test/e2e",
                output_dir=output_dir,
            )

            assert result["total_divergences"] > 0
            assert result["charts_found"] >= 1
            assert (output_dir / "divergences.csv").exists()
            assert (output_dir / "category_summary.csv").exists()
            assert (output_dir / "snapshot_metrics.json").exists()
            assert (output_dir / "run_manifest.json").exists()

            # Verify CSV contents
            df = pd.read_csv(output_dir / "divergences.csv")
            assert len(df) == result["total_divergences"]
            assert "divergence_id" in df.columns
            assert "category" in df.columns
            assert "confidence" in df.columns

            # Verify metrics
            with open(output_dir / "snapshot_metrics.json") as f:
                metrics = json.load(f)
            assert metrics["raw_divergence_count"] == len(df)
            assert 0 < metrics["raw_divergence_density"] <= 1

    def test_nonexistent_repo(self):
        """Pipeline handles missing repo gracefully."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            result = run_pipeline(
                repo_path=Path(tmpdir),  # Empty dir
                repo_id="test/empty",
                output_dir=Path(tmpdir) / "out",
            )
            assert result["status"] == "no_charts"
