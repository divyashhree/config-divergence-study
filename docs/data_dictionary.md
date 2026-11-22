# Data Dictionary

This document defines every field in every dataset produced by the pipeline.

## 1. `divergences.csv`

The core dataset — one row per observed configuration difference.

| Field | Type | Description |
|---|---|---|
| `divergence_id` | UUID | Unique identifier for this divergence observation |
| `repo_id` | String | Repository identifier (owner/name) |
| `commit_sha` | String | Git commit at which the snapshot was taken |
| `commit_date` | ISO 8601 | Timestamp of the snapshot commit |
| `env_pair` | String | Environment pair compared (e.g., "development::production" or "defaults::production") |
| `config_path` | String | Dot-delimited path to the configuration field (e.g., "resources.limits.cpu") |
| `diff_type` | Enum | Type of difference: `value_changed`, `key_missing_in_a`, `key_missing_in_b`, `type_changed`, `null_vs_value` |
| `category` | Enum | Taxonomy category: `replica_scaling`, `resource_limits`, `image_version`, `health_check`, `env_variable`, `security`, `networking`, `feature_flag`, `persistence`, `unknown` |
| `value_env_a` | String | Value in the first environment (may be `[REDACTED]`) |
| `value_env_b` | String | Value in the second environment (may be `[REDACTED]`) |
| `source_file_a` | String | File path of the first environment's values file |
| `source_file_b` | String | File path of the second environment's values file |
| `is_from_default` | Boolean | Whether at least one value is inherited from chart defaults (not explicitly set) |
| `default_value` | String | The chart default value, if applicable |
| `confidence` | Enum | Confidence in the observation: `high` (explicit values), `medium` (default inheritance or array matching), `low` (complex structure) |
| `typically_env_specific` | Boolean/null | Whether this category typically varies by environment (from taxonomy) |
| `total_comparable_paths` | Integer | Total number of configuration paths compared (denominator for density) |
| `evidence_notes` | String | Human-readable explanation of the difference context |
| `redacted` | Boolean | Whether any value was redacted due to sensitive key patterns |

## 2. `category_summary.csv`

Summary statistics by divergence category.

| Field | Type | Description |
|---|---|---|
| `category` | String | Taxonomy category name |
| `count` | Integer | Number of divergences in this category |
| `typically_env_specific` | Boolean | Whether this category typically varies by environment |
| `proportion` | Float | Proportion of total divergences (count / total) |

## 3. `env_pair_summary.csv`

Summary statistics by environment pair.

| Field | Type | Description |
|---|---|---|
| `env_pair` | String | Environment pair (e.g., "development::production") |
| `count` | Integer | Number of divergences for this pair |
| `density` | Float | Divergence density (count / total_comparable_paths) |

## 4. `snapshot_metrics.json`

Computed metrics for a single analysis snapshot.

| Field | Type | Description |
|---|---|---|
| `raw_divergence_count` | Integer | Total number of raw differences |
| `raw_divergence_density` | Float | raw_divergence_count / total_comparable_paths |
| `category_counts` | Object | {category: count} breakdown |
| `category_densities` | Object | {category: count/total_comparable_paths} |
| `high_confidence_count` | Integer | Divergences with confidence="high" |
| `from_default_count` | Integer | Divergences involving inherited defaults |
| `typically_env_specific_count` | Integer | Divergences in typically-varying categories |
| `total_comparable_paths` | Integer | Union of all configuration paths across compared environments |

## 5. `run_manifest.json`

Reproducibility record for each pipeline execution.

| Field | Type | Description |
|---|---|---|
| `run_id` | String | Unique 8-character run identifier |
| `repo_id` | String | Repository analyzed |
| `repo_path` | String | Local filesystem path |
| `commit_sha` | String | Git commit analyzed |
| `run_start` | ISO 8601 | Pipeline start time (UTC) |
| `run_end` | ISO 8601 | Pipeline end time (UTC) |
| `duration_seconds` | Float | Total execution time |
| `python_version` | String | Python version used |
| `charts_found` | Integer | Number of Helm chart directories found |
| `charts_with_envs` | Integer | Charts with environment-specific values |
| `total_divergences` | Integer | Total divergences extracted |
| `output_files` | Array | Paths to all generated output files |
| `chart_summaries` | Array | Per-chart processing details |

## 6. `annotations.csv` (Manual)

Independent reviewer classifications.

| Field | Type | Description |
|---|---|---|
| `annotation_id` | UUID | Unique annotation identifier |
| `divergence_id` | UUID | FK to divergences.divergence_id |
| `reviewer_id` | String | Reviewer identifier (e.g., "R1", "R2") |
| `label` | Enum | Classification: `intentional`, `accidental`, `suspicious`, `undetermined` |
| `reasoning` | String | Free-text explanation of the classification decision |
| `evidence_refs` | String | Comma-separated commit SHAs, URLs, or file paths |
| `annotated_at` | ISO 8601 | When the annotation was recorded |

## 7. `adjudications.csv` (Manual)

Resolved labels for disagreements between reviewers.

| Field | Type | Description |
|---|---|---|
| `divergence_id` | UUID | FK to divergences.divergence_id |
| `adjudicated_label` | Enum | Final resolved label |
| `adjudicator_id` | String | Who resolved the disagreement |
| `adjudication_reasoning` | String | Rationale for the resolution |
| `adjudicated_at` | ISO 8601 | When the adjudication was recorded |

## 8. `eligibility_assessment.csv`

Repository inclusion/exclusion decisions.

| Field | Type | Description |
|---|---|---|
| `repo_id` | String | Repository identifier |
| `eligible` | Boolean | Whether the repository meets inclusion criteria |
| `exclusion_reasons` | String | Semicolon-separated reasons for exclusion |
| `total_charts` | Integer | Number of Helm chart directories found |
| `total_environments` | Integer | Maximum number of environment-specific values files found |

## Metric Formulas

| Metric | Formula | Denominator |
|---|---|---|
| Raw divergence density | divergence_count / total_comparable_paths | Union of all config paths |
| Accidental divergence density | accidental_count / total_comparable_paths | Same |
| Suspicious divergence density | suspicious_count / total_comparable_paths | Same |
| Undetermined proportion | undetermined_count / total_divergences | Total divergences |
| Category density | category_count / total_comparable_paths | Same |
| Cohen's kappa | (p_observed - p_expected) / (1 - p_expected) | Per-label chance rates |
