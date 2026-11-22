# Methodology

## Study Design

This is an observational empirical study examining the association between environment configuration divergence and subsequent software maintenance activity in open-source Kubernetes projects.

**Study type:** Retrospective cohort study using public repository data.

**Unit of analysis:** Repository-snapshot (a single repository at a specific point in time).

## Sampling Strategy

### Repository Discovery
1. GitHub Code Search API queries for files matching environment-specific Helm values patterns (e.g., `values-prod.yaml`, `values-staging.yaml`)
2. Deduplication by repository
3. Metadata enrichment (stars, age, activity)

### Eligibility Criteria

**Inclusion:**
- Public GitHub repository
- Contains at least one Helm chart (Chart.yaml present)
- Has environment-specific values files for ≥1 environment (with chart defaults for comparison) or ≥2 distinct environments
- Has ≥180 days of git history
- Has ≥50 commits

**Exclusion:**
- Archived repositories
- Forked repositories (to avoid double-counting)
- Repositories with <5 stars (noise filter)
- Repositories where configuration files cannot be parsed

### Sampling Limitations
- Convenience sample from GitHub (not representative of all Kubernetes deployments)
- Only publicly visible configurations analyzed
- Naming-convention-based environment detection may miss non-standard patterns

## Measurement

### Independent Variable: Divergence Metrics

Measured at each snapshot (point in time):

1. **Raw divergence density** = (number of configuration differences) / (number of comparable paths)
2. **Category-specific counts** — per taxonomy category
3. **Classified densities** — after manual review (accidental, suspicious, undetermined densities)

### Dependent Variable: Maintenance Events

Measured in the observation window following each snapshot:

1. **Maintenance event count** — commits modifying configuration files
2. **Corrective event count** — subset classified as fixes, synchronizations, or rework

### Control Variables
- Repository age (days since first commit)
- Repository size (stars as proxy)
- Contributor count
- Number of environments
- Baseline maintenance rate (prior maintenance activity)
- Configuration complexity (total comparable paths)

## Analysis Plan

### RQ1 (Descriptive)
- Frequency distributions of divergence types and categories
- Repository-level and environment-pair comparisons
- Summary tables with counts, proportions, and uncertainty

### RQ2 (Classification Reliability)
- Two independent reviewers label a sample of divergences
- Cohen's kappa computed from original independent labels (before adjudication)
- Bootstrap 95% confidence interval for kappa
- Report raw agreement, label prevalence, and confusion matrix

### RQ3 (Association)
- Count regression model (Poisson or Negative Binomial based on overdispersion)
- Predictor: divergence density at snapshot
- Outcome: maintenance event count in observation window
- Controls: repository age, stars, contributors, environments, baseline rate
- Report incidence rate ratios with 95% CI

### RQ4 (Evolution)
- Temporal plots of divergence introduction, persistence, and resolution
- Selected case studies with documented evidence trails

### Robustness Checks
- Alternative observation windows (30, 90, 180 days)
- Alternative outcome (corrective events only)
- Excluding high-activity repositories
- Raw counts vs density
- With and without control variables

## Threats to Validity

### Internal Validity
- **Temporal leakage:** Mitigated by strict snapshot→window ordering
- **Confounding:** Addressed by control variables but not fully eliminated
- **Measurement validity:** Keyword-based event classification validated against manual sample

### External Validity
- Results apply to public GitHub Helm-based projects, not necessarily private or enterprise deployments
- Naming-convention-based environment detection may not generalize

### Construct Validity
- "Configuration divergence" is operationalized as structural differences between values files; some differences may be managed through other mechanisms (e.g., CI/CD variables)
- "Maintenance event" is operationalized through commit/PR analysis; some maintenance may occur without commits

### Reliability
- Inter-rater agreement (Cohen's kappa) explicitly measured and reported
- Pipeline is deterministic and reproducible from saved datasets
- All parameters documented in `config/study_config.yaml`
