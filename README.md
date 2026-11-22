# Environment Configuration Divergence in Cloud-Native Projects

**An Empirical Study of Maintenance Outcomes**

## Overview

This research system investigates whether differences between configurations used in development, staging, and production environments in Kubernetes-based projects are associated with subsequent software maintenance activity.

The system is designed for **research validity first** — it detects configuration differences automatically, establishes their context, classifies them with evidence, and tests their relationship with future maintenance. It does **not** conflate raw differences with defects.

## Research Questions

- **RQ1 (Characterization):** What types of configuration divergence occur across environments, and how frequently?
- **RQ2 (Classification reliability):** How reliably can independent reviewers distinguish intentional from potentially accidental divergence?
- **RQ3 (Maintenance association):** Is higher potentially accidental divergence associated with subsequent maintenance activity?
- **RQ4 (Evolution):** How does divergence evolve over time?

## Quick Start

### Prerequisites

- Python 3.12+
- Git 2.40+
- Dependencies: `pip install -r requirements.txt`

### Run Against Test Fixtures

```bash
cd config-divergence-study
python run_pipeline.py --fixtures
```

### Run Against a Real Repository

```bash
git clone https://github.com/<owner>/<repo>.git data/repos/<repo>
python run_pipeline.py --repo-path data/repos/<repo> --repo-id <owner>/<repo>
```

### Run the Full Analysis Pipeline

```bash
# Stage 5: Classification & maintenance event mining
python run_stage5.py

# Stage 6: Statistical analysis (RQ1-RQ4)
python run_stage6.py
```

### Run Tests

```bash
python -m pytest tests/ -v
# 131 tests, all passing
```

### Launch Dashboard

```bash
streamlit run dashboard/app.py
```

## Project Structure

```
config-divergence-study/
├── config/study_config.yaml     # Tunable study parameters
├── src/
│   ├── parsing/                 # YAML normalization, Helm parser
│   ├── divergence/              # Taxonomy, extraction, metrics
│   ├── classification/          # Labeling workflow, Cohen's kappa
│   ├── maintenance/             # Git history mining, event categorization
│   ├── longitudinal/            # Temporal dataset construction
│   ├── analysis/                # Descriptive and inferential statistics
│   ├── discovery/               # GitHub API search, eligibility assessment
│   └── utils/                   # Logging, secrets, git operations
├── tests/                       # 131 automated tests
│   ├── fixtures/                # Synthetic Helm chart fixtures
│   ├── test_normalizer.py       # 24 tests
│   ├── test_helm_parser.py      # 14 tests
│   ├── test_divergence.py       # 25 tests
│   ├── test_agreement.py        # 13 tests
│   └── test_stage5_6.py         # 37 tests (metrics, longitudinal, e2e)
├── dashboard/app.py             # Streamlit research dashboard (4 tabs)
├── data/
│   ├── outputs/                 # Per-repo pipeline outputs
│   ├── processed/               # Merged datasets, annotations, events
│   └── results/                 # RQ1-RQ4 analysis results & figures
├── docs/
│   ├── methodology.md           # Study design & analysis plan
│   ├── annotation_guide.md      # Reviewer labeling guide with examples
│   ├── data_dictionary.md       # All 8 dataset schemas documented
│   └── threats_to_validity.md   # 4 validity categories, 15 threats
├── run_pipeline.py              # Divergence extraction pipeline
├── run_stage5.py                # Classification & maintenance mining
├── run_stage6.py                # Full statistical analysis (RQ1-RQ4)
├── assess_repos.py              # Repository eligibility assessment
└── requirements.txt
```

## Key Design Decisions

### Five-Level Distinction

The system maintains strict separation between:
1. **Raw differences** — Any structural change between environments
2. **Potentially suspicious** — Differences in categories not typically environment-specific
3. **Strongly evidenced accidental** — Differences with evidence of unintentional origin
4. **Maintenance events** — Historical configuration changes with corrective evidence
5. **Associations** — Statistical relationships (never claimed as causal)

### Helm Semantics

- Chart default `values.yaml` is parsed and deep-merged with env-specific files
- Lists are replaced (not merged), matching Helm behavior
- Override tracking distinguishes explicit overrides from inherited defaults
- Secret values are redacted before storage

### Taxonomy Categories

| Category | Typically Env-Specific | Description |
|---|---|---|
| replica_scaling | Yes | Replica count and autoscaling |
| resource_limits | Yes | CPU/memory requests and limits |
| image_version | Yes | Container image tags |
| env_variable | Yes | Environment variables |
| networking | Yes | Service, ingress, host/port |
| persistence | Yes | Storage configuration |
| feature_flag | Yes | Component enablement |
| health_check | No | Liveness/readiness probes |
| security | No | TLS, RBAC, network policy |
| unknown | — | Uncategorized paths |

## Current Status

| Component | Status | Tests |
|---|---|---|
| YAML Normalizer | ✅ Complete | 24 passing |
| Helm Parser | ✅ Complete | 14 passing |
| Divergence Taxonomy | ✅ Complete | 16 passing |
| Divergence Extractor | ✅ Complete | 9 passing |
| Divergence Metrics | ✅ Complete | 7 passing |
| Classification Labeling | ✅ Complete | Used in pipeline |
| Cohen's Kappa | ✅ Complete | 13 passing |
| Maintenance Events | ✅ Complete | 14 passing |
| Longitudinal Dataset | ✅ Complete | 8 passing |
| Descriptive Statistics (RQ1) | ✅ Complete | Results saved |
| Classification Analysis (RQ2) | ✅ Complete | Kappa paradox documented |
| Association Analysis (RQ3) | ✅ Complete | Descriptive (insufficient n for regression) |
| Evolution Analysis (RQ4) | ✅ Complete | 2 case studies with figures |
| End-to-End Pipeline | ✅ Validated | 2 e2e tests passing |
| Real Repo Validation | ✅ 2 repos | podinfo (9 div), argocd-examples (1 div) |
| Streamlit Dashboard | ✅ Complete | 4 tabs with real data |
| Repository Discovery | ⚡ Built, needs API token | — |

## Key Findings

### RQ1: Divergence Distribution
- **10 divergences** across 2 repositories, 5 categories
- Most common: resource_limits (40%), replica_scaling (30%)
- All 10 divergences are high-confidence
- None inherited from defaults (all explicitly configured)

### RQ2: Classification Reliability
- **κ = 0.0, raw agreement = 70%** — Kappa paradox
- All divergences fall in typically-env-specific categories
- Reviewer A labels all as "intentional"; Reviewer B marks 3 as "suspicious" (missing resource limits, image repository path)
- **Finding:** In well-maintained Helm charts, most divergences are intentional. The kappa paradox itself reveals this pattern.

### RQ3: Maintenance Association
- 126 maintenance events mined (82 podinfo + 44 argocd-examples)
- Event breakdown: routine (96), unrelated (10), corrective_fix (8), sync (8), resource_tune (4)
- Insufficient observations for regression analysis (n=2 repos, both right-censored)

### RQ4: Evolution Patterns
- Podinfo: 9 divergences, 82 maintenance events (4 corrective)
- Argocd-examples: 1 divergence, 44 maintenance events (12 corrective including sync/rework)
- Higher corrective event ratio in argocd-examples (27%) vs podinfo (5%)

## Limitations

- **Sample size**: 2 eligible repos from 8 cloned; needs ≥30 for meaningful regression
- **Helm rendering**: Simplified (no subchart, no `--set` flag handling)
- **Kustomize**: Not yet implemented
- **Environment identification**: Relies on naming conventions
- **Maintenance classification**: Keyword-based categorization
- **Causation**: This study establishes associations, not causal relationships

## Documentation

- [Methodology](docs/methodology.md) — Study design, sampling, measurement, analysis plan
- [Annotation Guide](docs/annotation_guide.md) — Reviewer labeling instructions with worked examples
- [Data Dictionary](docs/data_dictionary.md) — All 8 dataset schemas with field types
- [Threats to Validity](docs/threats_to_validity.md) — 15 threats across 4 validity categories

## License

Research use. See methodology documentation for data provenance constraints.
