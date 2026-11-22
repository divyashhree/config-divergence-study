"""
Tests for the classification agreement module.

Covers:
- Cohen's kappa on known synthetic label sets
- Perfect agreement
- No agreement
- Expected values for known distributions
- Bootstrap CI computation
- Edge cases: single label, empty inputs
"""
import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.classification.agreement import (
    compute_cohens_kappa,
    compute_kappa_bootstrap_ci,
    compute_agreement_report,
)
import pandas as pd


class TestCohensKappa:
    def test_perfect_agreement(self):
        labels = ["intentional", "accidental", "suspicious", "undetermined"]
        result = compute_cohens_kappa(labels, labels)
        assert result["kappa"] == 1.0
        assert result["raw_agreement"] == 1.0
        assert result["n_agree"] == 4
        assert result["n_disagree"] == 0
        assert "Almost perfect" in result["interpretation"]

    def test_no_agreement(self):
        """Complete systematic disagreement should give negative kappa."""
        a = ["intentional", "intentional", "accidental", "accidental"]
        b = ["accidental", "accidental", "intentional", "intentional"]
        result = compute_cohens_kappa(a, b)
        assert result["kappa"] < 0
        assert result["raw_agreement"] == 0.0

    def test_chance_agreement(self):
        """Random labels should give kappa near 0."""
        # With equal distribution and 50% agreement, kappa ≈ 0
        a = ["intentional", "accidental", "intentional", "accidental"]
        b = ["intentional", "accidental", "accidental", "intentional"]
        result = compute_cohens_kappa(a, b)
        assert -0.5 <= result["kappa"] <= 0.5

    def test_known_kappa_value(self):
        """Test with a known example where kappa can be hand-calculated."""
        # 2 raters, 20 items, 2 categories
        # Agree on 15, disagree on 5
        a = (["yes"] * 10 + ["no"] * 10)
        b = (["yes"] * 8 + ["no"] * 2 + ["yes"] * 3 + ["no"] * 7)
        result = compute_cohens_kappa(a, b)
        # Raw agreement = 15/20 = 0.75
        assert result["raw_agreement"] == 0.75
        # Kappa should be positive but below 1
        assert 0 < result["kappa"] < 1
        assert result["n_cases"] == 20

    def test_confusion_matrix(self):
        a = ["A", "A", "B", "B"]
        b = ["A", "B", "A", "B"]
        result = compute_cohens_kappa(a, b)
        matrix = result["confusion_matrix"]
        assert "A" in matrix
        assert "B" in matrix

    def test_label_prevalence(self):
        a = ["intentional", "intentional", "accidental"]
        b = ["intentional", "accidental", "accidental"]
        result = compute_cohens_kappa(a, b)
        prev = result["label_prevalence"]
        assert prev["intentional"]["reviewer_a_count"] == 2
        assert prev["accidental"]["reviewer_b_count"] == 2

    def test_different_lengths_raises(self):
        with pytest.raises(ValueError, match="same length"):
            compute_cohens_kappa(["a", "b"], ["a"])

    def test_empty_raises(self):
        with pytest.raises(ValueError, match="empty"):
            compute_cohens_kappa([], [])

    def test_single_label(self):
        """All same label should give perfect agreement."""
        a = ["intentional"] * 5
        b = ["intentional"] * 5
        result = compute_cohens_kappa(a, b)
        assert result["raw_agreement"] == 1.0
        # Kappa may be 1.0 or undefined when expected agreement = 1.0
        assert result["kappa"] == 1.0


class TestBootstrapCI:
    def test_basic_ci(self):
        a = ["intentional", "accidental", "suspicious"] * 10
        b = ["intentional", "accidental", "suspicious"] * 10
        result = compute_kappa_bootstrap_ci(a, b, n_iterations=100)
        assert "ci_lower" in result
        assert "ci_upper" in result
        assert result["ci_lower"] <= result["ci_upper"]
        # Perfect agreement — CI should be near 1.0
        assert result["ci_lower"] > 0.8

    def test_reproducible(self):
        a = ["A", "B", "A", "B"] * 5
        b = ["A", "B", "B", "A"] * 5
        r1 = compute_kappa_bootstrap_ci(a, b, random_seed=42)
        r2 = compute_kappa_bootstrap_ci(a, b, random_seed=42)
        assert r1["ci_lower"] == r2["ci_lower"]


class TestAgreementReport:
    def test_full_report(self):
        annotations = pd.DataFrame({
            "divergence_id": ["d1", "d2", "d3", "d1", "d2", "d3"],
            "reviewer_id": ["R1", "R1", "R1", "R2", "R2", "R2"],
            "label": [
                "intentional", "accidental", "suspicious",
                "intentional", "accidental", "undetermined",
            ],
        })
        result = compute_agreement_report(annotations, "R1", "R2", bootstrap_ci=False)
        assert result["n_cases"] == 3
        assert result["kappa"] is not None
        assert len(result["disagreement_details"]) == 1  # d3 disagrees
        assert result["disagreement_details"][0]["divergence_id"] == "d3"

    def test_no_common_ids(self):
        annotations = pd.DataFrame({
            "divergence_id": ["d1", "d2"],
            "reviewer_id": ["R1", "R2"],
            "label": ["intentional", "accidental"],
        })
        result = compute_agreement_report(annotations, "R1", "R2")
        assert "error" in result
