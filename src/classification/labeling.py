"""
Manual annotation labeling workflow.

Provides tools for:
- Generating annotation tasks from divergence records
- Recording independent reviewer labels
- Storing labels with reasoning and evidence
- Tracking adjudication of disagreements
- Maintaining audit trail

Labels are stored as CSV for portability and versioning.
"""
import csv
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from src.utils.logging_config import get_logger

logger = get_logger("labeling")

VALID_LABELS = {"intentional", "accidental", "suspicious", "undetermined"}


def generate_annotation_tasks(
    divergences_path: Path,
    output_path: Path,
    sample_size: int | None = None,
    random_seed: int = 42,
    stratify_by: str = "category",
) -> pd.DataFrame:
    """
    Generate annotation task records from divergence data.

    Each task presents a divergence case with its evidence for labeling.
    Optionally samples a subset, stratified by category.

    Args:
        divergences_path: Path to divergences.csv.
        output_path: Where to save the annotation task file.
        sample_size: Number of cases to sample (None = all).
        random_seed: Seed for reproducible sampling.
        stratify_by: Column to stratify sampling by.

    Returns:
        DataFrame of annotation tasks.
    """
    df = pd.read_csv(divergences_path)
    logger.info(f"Loaded {len(df)} divergence records")

    if sample_size and sample_size < len(df):
        # Stratified sampling
        if stratify_by in df.columns:
            sampled = df.groupby(stratify_by, group_keys=False).apply(
                lambda x: x.sample(
                    n=min(len(x), max(1, sample_size // df[stratify_by].nunique())),
                    random_state=random_seed,
                ),
            )
            # Top up if needed
            if len(sampled) < sample_size:
                remaining = df[~df["divergence_id"].isin(sampled["divergence_id"])]
                extra = remaining.sample(
                    n=min(sample_size - len(sampled), len(remaining)),
                    random_state=random_seed,
                )
                sampled = pd.concat([sampled, extra])
            df = sampled.head(sample_size)
        else:
            df = df.sample(n=sample_size, random_state=random_seed)

    tasks = df[[
        "divergence_id", "repo_id", "env_pair", "config_path",
        "diff_type", "category", "value_env_a", "value_env_b",
        "source_file_a", "source_file_b", "is_from_default",
        "evidence_notes", "confidence", "typically_env_specific",
    ]].copy()

    tasks["case_number"] = range(1, len(tasks) + 1)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    tasks.to_csv(output_path, index=False)
    logger.info(f"Generated {len(tasks)} annotation tasks -> {output_path}")
    return tasks


def record_annotation(
    annotations_path: Path,
    divergence_id: str,
    reviewer_id: str,
    label: str,
    reasoning: str,
    evidence_refs: str = "",
) -> dict[str, Any]:
    """
    Record a single reviewer's annotation for a divergence case.

    Appends to the annotations CSV file.

    Args:
        annotations_path: Path to annotations CSV.
        divergence_id: Which divergence is being labeled.
        reviewer_id: Identifier for the reviewer.
        label: One of: intentional, accidental, suspicious, undetermined.
        reasoning: Free-text explanation.
        evidence_refs: Comma-separated commit SHAs, URLs, etc.

    Returns:
        The annotation record as a dict.

    Raises:
        ValueError: If label is invalid.
    """
    if label not in VALID_LABELS:
        raise ValueError(f"Invalid label '{label}'. Must be one of: {VALID_LABELS}")

    annotation = {
        "annotation_id": str(uuid.uuid4()),
        "divergence_id": divergence_id,
        "reviewer_id": reviewer_id,
        "label": label,
        "reasoning": reasoning,
        "evidence_refs": evidence_refs,
        "annotated_at": datetime.now(timezone.utc).isoformat(),
    }

    # Append to CSV
    annotations_path.parent.mkdir(parents=True, exist_ok=True)
    file_exists = annotations_path.exists()
    with open(annotations_path, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=annotation.keys())
        if not file_exists:
            writer.writeheader()
        writer.writerow(annotation)

    logger.info(f"Recorded annotation by {reviewer_id} for {divergence_id}: {label}")
    return annotation


def record_adjudication(
    adjudications_path: Path,
    divergence_id: str,
    adjudicated_label: str,
    adjudicator_id: str,
    reasoning: str,
) -> dict[str, Any]:
    """
    Record the adjudicated (resolved) label for a disagreement.

    Args:
        adjudications_path: Path to adjudications CSV.
        divergence_id: Divergence being adjudicated.
        adjudicated_label: Final label.
        adjudicator_id: Who resolved the disagreement.
        reasoning: Why this label was chosen.

    Returns:
        Adjudication record dict.
    """
    if adjudicated_label not in VALID_LABELS:
        raise ValueError(f"Invalid label '{adjudicated_label}'")

    record = {
        "divergence_id": divergence_id,
        "adjudicated_label": adjudicated_label,
        "adjudicator_id": adjudicator_id,
        "adjudication_reasoning": reasoning,
        "adjudicated_at": datetime.now(timezone.utc).isoformat(),
    }

    adjudications_path.parent.mkdir(parents=True, exist_ok=True)
    file_exists = adjudications_path.exists()
    with open(adjudications_path, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=record.keys())
        if not file_exists:
            writer.writeheader()
        writer.writerow(record)

    logger.info(f"Adjudicated {divergence_id}: {adjudicated_label} by {adjudicator_id}")
    return record


def load_annotations(annotations_path: Path) -> pd.DataFrame:
    """Load annotations from CSV."""
    if not annotations_path.exists():
        return pd.DataFrame(columns=[
            "annotation_id", "divergence_id", "reviewer_id",
            "label", "reasoning", "evidence_refs", "annotated_at",
        ])
    return pd.read_csv(annotations_path)


def find_disagreements(annotations: pd.DataFrame) -> pd.DataFrame:
    """
    Identify divergence cases where reviewers disagree.

    Returns DataFrame with divergence_id, reviewer labels, and disagreement flag.
    """
    if annotations.empty:
        return pd.DataFrame()

    # Pivot: one row per divergence, columns for each reviewer's label
    pivot = annotations.pivot_table(
        index="divergence_id",
        columns="reviewer_id",
        values="label",
        aggfunc="first",
    )

    # Find rows where not all labels agree
    if pivot.shape[1] < 2:
        logger.warning("Need at least 2 reviewers to detect disagreements")
        return pd.DataFrame()

    reviewer_cols = pivot.columns.tolist()
    pivot["labels_agree"] = pivot.apply(
        lambda row: len(set(row[reviewer_cols].dropna())) <= 1, axis=1
    )
    disagreements = pivot[~pivot["labels_agree"]].reset_index()
    return disagreements
