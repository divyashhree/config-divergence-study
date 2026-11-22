"""
Inferential statistics for RQ3.

Implements:
- Association between divergence metrics and maintenance event counts
- Count regression models (Poisson and Negative Binomial)
- Overdispersion tests
- Control variables
- Effect estimates with confidence intervals

Does NOT claim causation. All results are interpreted as associations.
"""
from typing import Any

import numpy as np
import pandas as pd

from src.utils.logging_config import get_logger

logger = get_logger("inferential")


def test_association(
    dataset: pd.DataFrame,
    predictor: str = "raw_divergence_density",
    outcome: str = "maintenance_event_count",
    controls: list[str] | None = None,
    model_type: str = "auto",
) -> dict[str, Any]:
    """
    Test the association between a divergence metric and maintenance activity.

    Args:
        dataset: Analysis dataset with predictor and outcome columns.
        predictor: Divergence metric column name.
        outcome: Maintenance outcome column name.
        controls: Optional list of control variable column names.
        model_type: 'poisson', 'negbin', or 'auto' (chooses based on overdispersion).

    Returns:
        Dict with model results, coefficients, CI, p-values, diagnostics.
    """
    try:
        import statsmodels.api as sm
        from statsmodels.discrete.discrete_model import Poisson, NegativeBinomial
    except ImportError:
        return {"error": "statsmodels not available"}

    # Validate data
    required_cols = [predictor, outcome]
    if controls:
        required_cols.extend(controls)

    missing_cols = [c for c in required_cols if c not in dataset.columns]
    if missing_cols:
        return {"error": f"Missing columns: {missing_cols}"}

    # Drop rows with NaN in relevant columns
    analysis_df = dataset[required_cols].dropna()
    n = len(analysis_df)

    if n < 5:
        return {
            "error": f"Insufficient observations: {n} (minimum 5 required)",
            "n_observations": n,
        }

    # Prepare X and y
    y = analysis_df[outcome].astype(float)
    X_cols = [predictor]
    if controls:
        X_cols.extend(controls)
    X = analysis_df[X_cols].astype(float)
    X = sm.add_constant(X)

    # Check for overdispersion to choose model
    mean_y = y.mean()
    var_y = y.var()
    overdispersion_ratio = var_y / max(mean_y, 1e-10)

    if model_type == "auto":
        model_type = "negbin" if overdispersion_ratio > 1.5 else "poisson"
        logger.info(
            f"Auto-selected {model_type} model "
            f"(mean={mean_y:.2f}, var={var_y:.2f}, ratio={overdispersion_ratio:.2f})"
        )

    # Fit model
    try:
        if model_type == "negbin":
            model = sm.NegativeBinomial(y, X)
            fit_result = model.fit(disp=0, maxiter=100)
        else:
            model = sm.Poisson(y, X)
            fit_result = model.fit(disp=0, maxiter=100)
    except Exception as e:
        return {
            "error": f"Model fitting failed: {str(e)}",
            "n_observations": n,
            "model_type": model_type,
        }

    # Extract results
    coefficients = {}
    for name, coef, se, pval in zip(
        fit_result.params.index,
        fit_result.params.values,
        fit_result.bse.values,
        fit_result.pvalues.values,
    ):
        ci = fit_result.conf_int().loc[name]
        coefficients[name] = {
            "coefficient": round(float(coef), 4),
            "std_error": round(float(se), 4),
            "p_value": round(float(pval), 6),
            "ci_lower": round(float(ci[0]), 4),
            "ci_upper": round(float(ci[1]), 4),
            "irr": round(float(np.exp(coef)), 4),  # Incidence Rate Ratio
            "irr_ci_lower": round(float(np.exp(ci[0])), 4),
            "irr_ci_upper": round(float(np.exp(ci[1])), 4),
        }

    return {
        "model_type": model_type,
        "n_observations": n,
        "predictor": predictor,
        "outcome": outcome,
        "controls": controls or [],
        "coefficients": coefficients,
        "aic": round(float(fit_result.aic), 2),
        "bic": round(float(fit_result.bic), 2),
        "log_likelihood": round(float(fit_result.llf), 2),
        "overdispersion_ratio": round(float(overdispersion_ratio), 4),
        "mean_outcome": round(float(mean_y), 4),
        "var_outcome": round(float(var_y), 4),
        "converged": fit_result.mle_retvals.get("converged", None),
        "interpretation": _interpret_result(
            coefficients.get(predictor, {}), predictor, outcome, model_type
        ),
    }


def run_robustness_checks(
    dataset: pd.DataFrame,
    predictor: str = "raw_divergence_density",
    outcome: str = "maintenance_event_count",
    controls: list[str] | None = None,
    alternative_windows: list[int] | None = None,
) -> list[dict[str, Any]]:
    """
    Run robustness checks with alternative specifications.

    Checks include:
    - Alternative outcome (corrective_event_count)
    - With and without controls
    - Excluding high-activity repositories
    - Alternative divergence measures
    """
    checks = []

    # 1. Base model
    base = test_association(dataset, predictor, outcome, controls)
    base["check_name"] = "base_model"
    checks.append(base)

    # 2. Without controls
    if controls:
        no_controls = test_association(dataset, predictor, outcome, controls=None)
        no_controls["check_name"] = "no_controls"
        checks.append(no_controls)

    # 3. Alternative outcome (corrective only)
    if "corrective_event_count" in dataset.columns:
        corrective = test_association(
            dataset, predictor, "corrective_event_count", controls
        )
        corrective["check_name"] = "corrective_outcome_only"
        checks.append(corrective)

    # 4. Exclude top 10% most active repos
    if "maintenance_event_count" in dataset.columns and len(dataset) >= 10:
        threshold = dataset["maintenance_event_count"].quantile(0.9)
        filtered = dataset[dataset["maintenance_event_count"] <= threshold]
        if len(filtered) >= 5:
            exclude_active = test_association(filtered, predictor, outcome, controls)
            exclude_active["check_name"] = "exclude_high_activity"
            exclude_active["n_excluded"] = len(dataset) - len(filtered)
            checks.append(exclude_active)

    # 5. Raw count instead of density
    if "raw_divergence_count" in dataset.columns and predictor != "raw_divergence_count":
        raw_count = test_association(
            dataset, "raw_divergence_count", outcome, controls
        )
        raw_count["check_name"] = "raw_count_predictor"
        checks.append(raw_count)

    logger.info(f"Completed {len(checks)} robustness checks")
    return checks


def _interpret_result(
    coef_info: dict, predictor: str, outcome: str, model_type: str,
) -> str:
    """Generate a careful interpretation of the statistical result."""
    if not coef_info:
        return "Model did not produce a coefficient for the predictor."

    p = coef_info.get("p_value", 1.0)
    irr = coef_info.get("irr", 1.0)
    irr_lo = coef_info.get("irr_ci_lower", 0)
    irr_hi = coef_info.get("irr_ci_upper", 0)

    if p < 0.001:
        sig = "statistically significant (p < 0.001)"
    elif p < 0.01:
        sig = f"statistically significant (p = {p:.4f})"
    elif p < 0.05:
        sig = f"statistically significant (p = {p:.4f})"
    else:
        sig = f"not statistically significant (p = {p:.4f})"

    direction = "positively" if irr > 1 else "negatively" if irr < 1 else "not"

    return (
        f"The {model_type} model indicates a {sig} {direction} "
        f"association between {predictor} and {outcome}. "
        f"IRR = {irr:.3f} (95% CI: {irr_lo:.3f}–{irr_hi:.3f}). "
        f"This is an observational association and should not be "
        f"interpreted as evidence of a causal relationship."
    )
