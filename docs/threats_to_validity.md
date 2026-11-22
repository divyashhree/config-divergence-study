# Threats to Validity

## Internal Validity

### Selection Bias
- **Threat:** Repositories were selected through convenience sampling (GitHub search + 
  manual identification), not random sampling from a defined population.
- **Mitigation:** Transparent eligibility criteria with documented exclusion reasons. 
  All criteria are automated and reproducible via `assess_repos.py`.
- **Residual Risk:** Results may not generalize to all Helm-based projects.

### Measurement Validity
- **Threat:** Structural YAML differencing may miss semantic equivalences (e.g., 
  `1000m` vs `1` for CPU, or `1Gi` vs `1024Mi` for memory).
- **Mitigation:** Confidence scores flag uncertainty. High-confidence divergences
  require exact structural differences. All measurements documented in `data_dictionary.md`.
- **Residual Risk:** Some semantically equivalent configurations may be counted as divergences.

### Classification Reliability
- **Threat:** Intent classification (intentional vs accidental) is subjective.
- **Mitigation:** Two independent reviewers with Cohen's kappa measurement. Annotation
  guide with worked examples. Adjudication process for disagreements.
- **Observed Result:** Kappa paradox observed (κ=0.0 with 70% raw agreement) due to 
  extreme label skew — nearly all observed divergences fall in typically-env-specific 
  categories and are classified as intentional. This is itself a finding: in well-maintained
  Helm charts, most configuration differences between environments are deliberate.

### Confounding Variables
- **Threat:** Association between divergence and maintenance could be driven by project
  activity level, not by divergence itself.
- **Mitigation:** Baseline maintenance rate computed as a control. Count regression includes
  repo-level controls (stars, contributors, age). Robustness checks with alternative
  specifications.
- **Residual Risk:** With only 2 eligible repositories, regression analysis was not feasible.
  Results are descriptive, not inferential.

### Temporal Ordering
- **Threat:** Using future information to predict outcomes (data leakage).
- **Mitigation:** Strict temporal ordering enforced: divergence measured at time t, 
  maintenance counted in [t, t+90 days]. Right-censoring excludes repos with insufficient
  post-snapshot data. Validated by `validate_temporal_ordering()`.

## External Validity

### Generalizability
- **Threat:** Results from 2 open-source Helm repositories may not generalize to:
  - Enterprise/private repositories
  - Non-Helm configuration management (Kustomize, plain YAML, Terraform)
  - Different domains (not cloud-native)
- **Mitigation:** Methodology is designed to be replicable with any Helm-based repository.
  Pipeline is parameterized and documented for independent replication.

### Environment Representation
- **Threat:** Most real-world multi-environment setups exist in deployment/GitOps repos,
  not chart authoring repos. Our 25% eligibility rate reflects this.
- **Mitigation:** Documented as a known constraint. Recommended that future work target
  GitOps repos (ArgoCD, Flux) rather than chart source repos.

## Construct Validity

### Divergence ≠ Defect
- **Threat:** Readers may interpret any configuration difference as a problem.
- **Mitigation:** Five-level distinction enforced throughout: raw differences → suspicious → 
  evidenced accidental → maintenance events → associations. Category labels indicate type, 
  not intent. Dashboard clearly labels this distinction.

### Maintenance Events as Proxy
- **Threat:** Commit message keyword matching is an imperfect proxy for actual maintenance effort.
- **Mitigation:** Six-category event taxonomy with transparent keyword lists. Categories
  distinguished: corrective_fix, sync, rework, resource_tune, routine, unrelated.
  Deduplication groups related commits into logical episodes.
- **Residual Risk:** Some routine updates may be miscategorized as corrective, and vice versa.

### Intentionality Classification
- **Threat:** The `typically_env_specific` flag in the taxonomy is a heuristic prior, not
  ground truth about any specific divergence.
- **Mitigation:** The flag is used only as evidence for classification, never as a final label.
  Human reviewers make the final determination with documented reasoning.

## Statistical Conclusion Validity

### Sample Size
- **Threat:** With n=10 divergences across 2 repos, statistical power is very low.
  Regression analysis requires ≥5 observations and was not feasible.
- **Mitigation:** Findings are reported as descriptive patterns, not statistical claims.
  The methodology demonstrates what would be possible with a larger sample.
- **Recommended:** Future work should target ≥30 repositories with ≥100 divergences
  for meaningful regression analysis.

### Kappa Paradox
- **Threat:** Cohen's κ=0.0 despite 70% agreement is misleading if interpreted naively.
- **Mitigation:** Kappa paradox explicitly documented. Occurs because reviewer A labels
  all cases as "intentional" (reflecting that all observed divergences are in env-specific
  categories), making expected agreement = observed agreement. The paradox itself is
  informative: it suggests that in well-maintained charts, finding accidental divergences
  is rare, which limits the applicability of intent classification schemes.

### Multiple Comparisons
- **Threat:** Not applicable with current sample size, but would be relevant at scale.
- **Mitigation:** Bonferroni or FDR correction recommended for future work with
  multiple category-level tests.

## Reliability

### Reproducibility
- **Threat:** Results depend on specific repository states at analysis time.
- **Mitigation:** Run manifests record commit SHA, timestamps, Python version, and all
  parameters. Pipeline is deterministic given the same inputs. Random seeds fixed for
  sampling (seed=42).
- **Artifact:** `run_manifest.json` in every output directory.

### Tool Reliability
- **Threat:** Bugs in parsing, classification, or analysis code.
- **Mitigation:** 131 automated tests covering parsing, taxonomy, agreement, metrics,
  longitudinal dataset construction, event categorization, deduplication, and 
  end-to-end pipeline execution. All tests pass.
