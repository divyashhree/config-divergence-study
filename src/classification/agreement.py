"""
Inter-rater agreement analysis.

Computes Cohen's kappa and related agreement statistics
from independent reviewer labels (BEFORE adjudication).

Reports:
- Raw percentage agreement
- Cohen's kappa with interpretation
- Confusion matrix
- Label prevalence
- Confidence intervals (bootstrap) when feasible
"""
import numpy as np
import pandas as pd
from typing import Any

from src.utils.logging_config import get_logger

logger = get_logger("agreement")


def compute_cohens_kappa(
    labels_a: list[str],
    labels_b: list[str],
) -> dict[str, Any]:
    """
    Compute Cohen's kappa for two sets of labels.

    Uses the original independent labels, NOT adjudicated labels.

    Args:
        labels_a: Labels from reviewer A.
        labels_b: Labels from reviewer B (same length, same order).

    Returns:
        Dict with kappa, raw_agreement, expected_agreement,
        confusion_matrix, label_prevalence, interpretation.

    Raises:
        ValueError: If inputs have different lengths or are empty.
    """
    if len(labels_a) != len(labels_b):
        raise ValueError(
            f"Label lists must be same length: {len(labels_a)} vs {len(labels_b)}"
        )
    if len(labels_a) == 0:
        raise ValueError("Cannot compute kappa on empty label lists")

    n = len(labels_a)
    all_labels = sorted(set(labels_a) | set(labels_b))

    # Build confusion matrix
    matrix = {}
    for la in all_labels:
        matrix[la] = {}
        for lb in all_labels:
            matrix[la][lb] = 0

    for la, lb in zip(labels_a, labels_b):
        matrix[la][lb] += 1

    # Raw agreement (proportion where both reviewers agree)
    agree_count = sum(1 for a, b in zip(labels_a, labels_b) if a == b)
    raw_agreement = agree_count / n

    # Expected agreement by chance
    # P(both choose label k by chance) = P(A=k) * P(B=k)
    expected = 0.0
    label_prevalence = {}
    for label in all_labels:
        count_a = sum(1 for x in labels_a if x == label)
        count_b = sum(1 for x in labels_b if x == label)
        p_a = count_a / n
        p_b = count_b / n
        expected += p_a * p_b
        label_prevalence[label] = {
            "reviewer_a_count": count_a,
            "reviewer_a_proportion": round(p_a, 4),
            "reviewer_b_count": count_b,
            "reviewer_b_proportion": round(p_b, 4),
        }

    # Cohen's kappa
    if expected == 1.0:
        # Perfect expected agreement — kappa is undefined
        kappa = 1.0 if raw_agreement == 1.0 else 0.0
    else:
        kappa = (raw_agreement - expected) / (1.0 - expected)

    # Convert confusion matrix to DataFrame for readability
    confusion_df = pd.DataFrame(matrix).T
    confusion_df.index.name = "Reviewer A"
    confusion_df.columns.name = "Reviewer B"

    return {
        "kappa": round(kappa, 4),
        "raw_agreement": round(raw_agreement, 4),
        "expected_agreement": round(expected, 4),
        "n_cases": n,
        "n_agree": agree_count,
        "n_disagree": n - agree_count,
        "confusion_matrix": confusion_df.to_dict(),
        "label_prevalence": label_prevalence,
        "all_labels": all_labels,
        "interpretation": _interpret_kappa(kappa),
    }


def compute_kappa_bootstrap_ci(
    labels_a: list[str],
    labels_b: list[str],
    n_iterations: int = 1000,
    confidence: float = 0.95,
    random_seed: int = 42,
) -> dict[str, float]:
    """
    Compute bootstrap confidence interval for Cohen's kappa.

    Args:
        labels_a: Labels from reviewer A.
        labels_b: Labels from reviewer B.
        n_iterations: Number of bootstrap samples.
        confidence: Confidence level (e.g., 0.95 for 95%).
        random_seed: For reproducibility.

    Returns:
        Dict with ci_lower, ci_upper, kappa_mean, kappa_std.
    """
    rng = np.random.RandomState(random_seed)
    n = len(labels_a)
    kappas = []

    for _ in range(n_iterations):
        indices = rng.choice(n, size=n, replace=True)
        sample_a = [labels_a[i] for i in indices]
        sample_b = [labels_b[i] for i in indices]
        try:
            result = compute_cohens_kappa(sample_a, sample_b)
            kappas.append(result["kappa"])
        except (ValueError, ZeroDivisionError):
            continue

    if not kappas:
        return {
            "ci_lower": float("nan"),
            "ci_upper": float("nan"),
            "kappa_mean": float("nan"),
            "kappa_std": float("nan"),
        }

    alpha = 1 - confidence
    lower = np.percentile(kappas, 100 * alpha / 2)
    upper = np.percentile(kappas, 100 * (1 - alpha / 2))

    return {
        "ci_lower": round(float(lower), 4),
        "ci_upper": round(float(upper), 4),
        "kappa_mean": round(float(np.mean(kappas)), 4),
        "kappa_std": round(float(np.std(kappas)), 4),
    }


def compute_agreement_report(
    annotations: pd.DataFrame,
    reviewer_a_id: str,
    reviewer_b_id: str,
    bootstrap_ci: bool = True,
    n_bootstrap: int = 1000,
) -> dict[str, Any]:
    """
    Generate a complete agreement report from annotation data.

    Uses ONLY the original independent labels (before adjudication).

    Args:
        annotations: DataFrame with divergence_id, reviewer_id, label columns.
        reviewer_a_id: ID of first reviewer.
        reviewer_b_id: ID of second reviewer.
        bootstrap_ci: Whether to compute bootstrap confidence interval.
        n_bootstrap: Bootstrap iterations.

    Returns:
        Comprehensive agreement report dict.
    """
    # Filter to the two reviewers
    a_labels = annotations[annotations["reviewer_id"] == reviewer_a_id].set_index("divergence_id")["label"]
    b_labels = annotations[annotations["reviewer_id"] == reviewer_b_id].set_index("divergence_id")["label"]

    # Find common divergence IDs (both reviewers must have labeled)
    common_ids = sorted(set(a_labels.index) & set(b_labels.index))

    if len(common_ids) == 0:
        return {
            "error": "No common divergence IDs between reviewers",
            "reviewer_a_count": len(a_labels),
            "reviewer_b_count": len(b_labels),
        }

    labels_a = [a_labels[did] for did in common_ids]
    labels_b = [b_labels[did] for did in common_ids]

    # Compute kappa
    kappa_result = compute_cohens_kappa(labels_a, labels_b)

    # Add bootstrap CI if requested
    ci_result = None
    if bootstrap_ci and len(common_ids) >= 10:
        ci_result = compute_kappa_bootstrap_ci(
            labels_a, labels_b, n_iterations=n_bootstrap,
        )
        kappa_result["bootstrap_ci"] = ci_result
    elif len(common_ids) < 10:
        kappa_result["bootstrap_ci_note"] = (
            f"Bootstrap CI not computed: only {len(common_ids)} cases "
            f"(minimum 10 recommended)"
        )

    # Identify specific disagreements
    disagreements = []
    for i, did in enumerate(common_ids):
        if labels_a[i] != labels_b[i]:
            disagreements.append({
                "divergence_id": did,
                "label_a": labels_a[i],
                "label_b": labels_b[i],
            })
    kappa_result["disagreement_details"] = disagreements

    # Warn about rare labels
    for label, prev in kappa_result["label_prevalence"].items():
        total = prev["reviewer_a_count"] + prev["reviewer_b_count"]
        if total <= 2:
            kappa_result.setdefault("warnings", []).append(
                f"Label '{label}' is very rare ({total} occurrences total). "
                f"Kappa may be unstable."
            )

    kappa_result["reviewer_a_id"] = reviewer_a_id
    kappa_result["reviewer_b_id"] = reviewer_b_id

    return kappa_result


def _interpret_kappa(kappa: float) -> str:
    """
    Interpret kappa value using Landis & Koch (1977) benchmarks.

    Note: These benchmarks are conventions, not rigid thresholds.
    """
    if kappa < 0:
        return "Poor (less than chance agreement)"
    elif kappa < 0.21:
        return "Slight agreement"
    elif kappa < 0.41:
        return "Fair agreement"
    elif kappa < 0.61:
        return "Moderate agreement"
    elif kappa < 0.81:
        return "Substantial agreement"
    else:
        return "Almost perfect agreement"
