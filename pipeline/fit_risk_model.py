"""
Fit a Negative Binomial SPF (Safety Performance Function) to the Capitol Hill
intersection dataset.

Follows AASHTO Highway Safety Manual methodology for count-based safety
modeling: NB2 family (variance = mu + alpha·mu²), log link, offset =
log(years_observed) to account for the 6-year observation window.

KNOWN LIMITATION — no AADT exposure term:
  Traffic volume (AADT) is the standard SPF exposure variable but is not
  available in usable form in this dataset. Infrastructure features
  (arterial class, speed limit, signal presence) will partially proxy for
  volume, biasing their coefficients upward relative to a fully-specified
  model. This is a documented MVP compromise. The model can be re-fit once
  a usable AADT layer is joined; add log(aadt) as an offset or predictor.

Inputs
------
data/intermediate/intersection_features.parquet  — built by assemble_features.py
data/intermediate/crashes_by_intersection.parquet — built by snap_crashes.py

Outputs
-------
data/intermediate/intersection_predictions.parquet
    651 rows: intersection_id, expected_total, expected_crashes_per_year,
    actual_total, residual, model_version, fitted_at

data/model/nb_v1_no_aadt.pkl
    Fitted statsmodels NegativeBinomialResults object (pickle via .save())

Run after : python pipeline/assemble_features.py
Run before: python pipeline/export_to_supabase.py
"""

import sys
import warnings
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from statsmodels.tools.sm_exceptions import ConvergenceWarning

import numpy as np
import pandas as pd
import statsmodels.formula.api as smf

ROOT = Path(__file__).resolve().parent.parent
FEATURES_PATH    = ROOT / "data" / "intermediate" / "intersection_features.parquet"
CRASHES_PATH     = ROOT / "data" / "intermediate" / "crashes_by_intersection.parquet"
PREDICTIONS_PATH = ROOT / "data" / "intermediate" / "intersection_predictions.parquet"
MODEL_DIR        = ROOT / "data" / "model"
MODEL_PATH       = MODEL_DIR / "nb_v1_no_aadt.pkl"

MODEL_VERSION = "nb_v1_no_aadt"

# is_arterial is EXCLUDED: it is a perfect linear combination of
# C(arterial_class) dummies (is_arterial==1 iff arterial_class>0), so
# including both causes perfect collinearity and blows up standard errors.
# C(arterial_class) alone encodes both "is it an arterial" and "what class":
#   baseline = 0 (non-arterial/local)
#   T.1–T.5 = principal, minor, collector, NOS arterial (non-contiguous;
#   categorical dummies avoid the false equal-spacing of an ordinal term).
FORMULA = (
    "total_crashes ~ is_signalized + num_legs + max_speed_limit"
    " + bike_facility + C(arterial_class)"
)

AADT_CAVEAT = """\
╔══════════════════════════════════════════════════════════════════════╗
║  MVP LIMITATION — AADT (traffic volume) excluded from this model    ║
║                                                                      ║
║  AADT is the standard SPF exposure variable (AASHTO HSM §3).        ║
║  It was dropped because the available AADT layer produced near-zero  ║
║  spatial coverage over Capitol Hill intersections.                   ║
║                                                                      ║
║  Consequence: C(arterial_class) and max_speed_limit                  ║
║  are absorbing the missing volume signal in addition to their own    ║
║  infrastructure effect.  Their coefficients are expected to be       ║
║  inflated vs. a fully-specified model.  Do NOT interpret them as     ║
║  pure infrastructure effects.                                        ║
║                                                                      ║
║  Planned fix: add log(aadt) as an offset or predictor once a usable  ║
║  AADT join is available.                                             ║
╚══════════════════════════════════════════════════════════════════════╝"""


# ---------------------------------------------------------------------------
# Load + join
# ---------------------------------------------------------------------------

def load_and_join() -> pd.DataFrame:
    """
    Load features and crash counts; inner-join on intersection_id.
    Asserts exactly 651 rows; stops with a diagnostic message if not.
    """
    missing = []
    if not FEATURES_PATH.exists():
        missing.append(
            f"  {FEATURES_PATH}  →  run: python pipeline/assemble_features.py"
        )
    if not CRASHES_PATH.exists():
        missing.append(
            f"  {CRASHES_PATH}  →  run: python pipeline/snap_crashes.py"
        )
    if missing:
        sys.exit("[ERROR] Missing required inputs:\n" + "\n".join(missing))

    features = pd.read_parquet(FEATURES_PATH)
    crashes  = pd.read_parquet(CRASHES_PATH)
    df = features.merge(crashes, on="intersection_id", how="inner")

    if len(df) != 651:
        feat_ids  = set(features["intersection_id"])
        crash_ids = set(crashes["intersection_id"])
        msg = f"[ERROR] Inner join produced {len(df)} rows, expected 651.\n"
        only_feat  = feat_ids - crash_ids
        only_crash = crash_ids - feat_ids
        if only_feat:
            sample = sorted(only_feat)[:5]
            msg += f"  In features but not crashes ({len(only_feat)}): {sample} ...\n"
        if only_crash:
            sample = sorted(only_crash)[:5]
            msg += f"  In crashes but not features ({len(only_crash)}): {sample} ...\n"
        sys.exit(msg)

    return df


# ---------------------------------------------------------------------------
# Prepare
# ---------------------------------------------------------------------------

def prepare(df: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """
    Clean the joined frame for modelling.

    Steps:
      1. Drop max_aadt (all-NaN, intentionally excluded; see module docstring).
      2. Validate years_observed == 6; warn (do not stop) if any differ.
      3. Build log-offset column.
      4. Assert zero NaN in binary/count features — NaN here is a regression.
      5. Fill max_speed_limit NaN with median if any exist (unexpected; counted).

    Returns (cleaned_df, stats) where stats is consumed by __main__ for printing.
    """
    df = df.copy()

    # 1. Drop AADT — excluded from MVP model (see module docstring)
    df = df.drop(columns=["max_aadt"], errors="ignore")

    # 2. Offset: validate exposure window
    bad_obs = df[df["years_observed"] != 6][["intersection_id", "years_observed"]]
    df["offset"] = np.log(df["years_observed"])

    # 3. Binary / integer features must be fully populated after assemble_features.py
    must_be_clean = [
        "is_signalized", "num_legs", "is_arterial", "arterial_class", "bike_facility",
    ]
    dirty = {
        col: df.loc[df[col].isna(), "intersection_id"].tolist()
        for col in must_be_clean
        if df[col].isna().any()
    }
    if dirty:
        msg = (
            "[ERROR] Unexpected NaN in features that were clean after assemble_features.py.\n"
            "This indicates a regression upstream — fix assemble_features.py and re-run.\n"
        )
        for col, ids in dirty.items():
            msg += f"  {col}: {ids}\n"
        sys.exit(msg)

    # 4. max_speed_limit: fill median if any NaN (should be 0 after assemble_features.py)
    n_speed_nan = int(df["max_speed_limit"].isna().sum())
    if n_speed_nan:
        median_speed = df["max_speed_limit"].median()
        df["max_speed_limit"] = df["max_speed_limit"].fillna(median_speed)
    else:
        median_speed = None

    stats = {
        "n_speed_nan":  n_speed_nan,
        "median_speed": median_speed,
        "bad_obs":      bad_obs,
    }
    return df, stats


# ---------------------------------------------------------------------------
# Fit
# ---------------------------------------------------------------------------

def fit_model(df: pd.DataFrame):
    """
    Fit NB2 via statsmodels formula API with log-offset for exposure.

    Retries with method='bfgs', maxiter=200 if the first attempt fails.
    Convergence requires BOTH mle_retvals['converged']==True AND no
    ConvergenceWarning — a warning on the final fit is treated as failure
    so it cannot silently produce an invalid result.
    """
    model = smf.negativebinomial(FORMULA, data=df, offset=df["offset"].values)

    def _fit_capturing_warnings(**kwargs):
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            res = model.fit(**kwargs)
        conv_warns = [w for w in caught if issubclass(w.category, ConvergenceWarning)]
        return res, conv_warns

    def _is_converged(res, conv_warns: list) -> bool:
        return (not conv_warns) and res.mle_retvals.get("converged", True)

    result, warns = _fit_capturing_warnings(disp=False)
    if not _is_converged(result, warns):
        result, warns = _fit_capturing_warnings(method="bfgs", maxiter=200, disp=False)
        if not _is_converged(result, warns):
            print(result.summary())
            print(f"\nmle_retvals: {result.mle_retvals}")
            if warns:
                print(f"ConvergenceWarnings: {[str(w.message) for w in warns]}")
            sys.exit(
                "[ERROR] Model did not converge after BFGS retry "
                "(see summary + mle_retvals above).  Outputs not written."
            )

    return result


# ---------------------------------------------------------------------------
# Validate
# ---------------------------------------------------------------------------

def validate(result, df: pd.DataFrame) -> pd.DataFrame:
    """
    Compute predictions on the response (count) scale and attach residuals.

    Uses result.predict(df, offset=...) so the inverse log-link AND the
    exposure offset are both applied — fittedvalues returns the linear
    predictor (log scale) and must NOT be used directly here.

    Asserts all expected_total >= 0 and that the sum is within 15% of the
    actual total before returning.  Stops with a diagnostic if either fails.
    """
    # Carry severity sub-counts through for the Vision Zero scorecard downstream.
    severity_cols = [c for c in ("injury_total", "ksi_total", "fatal_total",
                                  "ped_total", "bike_total") if c in df.columns]
    out = df[["intersection_id", "total_crashes", "years_observed"] + severity_cols].copy()

    # predict() applies exp(X @ beta + offset) — response scale, always >= 0
    out["expected_total"] = result.predict(df, offset=df["offset"].values)

    # Guard: count model with log link cannot produce negatives
    n_negative = int((out["expected_total"] < 0).sum())
    if n_negative:
        print(out[["intersection_id", "expected_total"]].head(10).to_string(index=False))
        sys.exit(
            f"[ERROR] {n_negative} expected_total values are negative — "
            "prediction is not on the response scale.  Outputs not written."
        )

    # Guard: a well-specified count model conserves the total within ~15%
    sum_pred   = float(out["expected_total"].sum())
    sum_actual = int(out["total_crashes"].sum())
    pct_diff   = abs(sum_pred - sum_actual) / sum_actual * 100
    if pct_diff > 15:
        print(out[["intersection_id", "total_crashes", "expected_total"]].head(10).to_string(index=False))
        sys.exit(
            f"[ERROR] Calibration failed: sum(predicted)={sum_pred:.1f} vs "
            f"sum(actual)={sum_actual} ({pct_diff:.1f}% gap > 15% threshold).  "
            "Outputs not written."
        )

    out["expected_crashes_per_year"] = out["expected_total"] / out["years_observed"]
    out["actual_total"]              = out["total_crashes"].astype(int)
    out["residual"]                  = out["actual_total"] - out["expected_total"]
    return out.drop(columns=["total_crashes"])


# ---------------------------------------------------------------------------
# Write outputs
# ---------------------------------------------------------------------------

def write_outputs(result, predictions: pd.DataFrame) -> None:
    """Write predictions parquet and the serialized model."""
    out = predictions.drop(columns=["years_observed"]).copy()
    out["model_version"] = MODEL_VERSION
    out["fitted_at"]     = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    PREDICTIONS_PATH.parent.mkdir(parents=True, exist_ok=True)
    out.to_parquet(PREDICTIONS_PATH, index=False)

    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    result.save(str(MODEL_PATH))


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # 1. Load + join
    df = load_and_join()
    print(f"Joined dataset: {len(df)} rows (expect 651).\n")

    # 2. Prepare
    df, prep_stats = prepare(df)

    # Print preparation diagnostics
    if len(prep_stats["bad_obs"]):
        print(f"[WARN] {len(prep_stats['bad_obs'])} rows have years_observed != 6:")
        print(prep_stats["bad_obs"].to_string(index=False))
    else:
        print("years_observed: all 651 rows == 6.  Good.")

    n_speed = prep_stats["n_speed_nan"]
    if n_speed:
        print(
            f"[WARN] Filled {n_speed} NaN in max_speed_limit with median "
            f"({prep_stats['median_speed']}).  Unexpected — check assemble_features.py."
        )
    else:
        print("max_speed_limit: fully populated (0 NaN).  Good.")

    # Print AADT caveat early so it cannot be missed
    print(f"\n{AADT_CAVEAT}\n")

    # 3. Fit
    print("Fitting NegativeBinomial model...")
    result = fit_model(df)
    print("Convergence: OK\n")

    # 4. Validate + print
    predictions = validate(result, df)

    # Full model summary
    print("=" * 70)
    print(result.summary())
    print("=" * 70)

    # Alpha / overdispersion
    alpha: Optional[float] = None
    if "alpha" in result.params.index:
        alpha = float(result.params["alpha"])
    elif hasattr(result, "alpha"):
        alpha = float(result.alpha)

    print("\n--- Dispersion parameter ---")
    if alpha is not None:
        if alpha > 0.05:
            verdict = (
                "alpha significantly > 0 — overdispersion confirmed.  "
                "NB is the correct family; Poisson would have underestimated variance."
            )
        else:
            verdict = (
                f"alpha ≈ 0 ({alpha:.4f}) — Poisson may have sufficed.  "
                "Consider comparing AIC between NB and Poisson fits."
            )
        print(f"alpha = {alpha:.4f}")
        print(verdict)
    else:
        print("[WARN] Could not extract alpha from fitted result — inspect result.params above.")

    # Calibration
    sum_pred   = float(predictions["expected_total"].sum())
    sum_actual = int(predictions["actual_total"].sum())
    pct_diff   = 100.0 * (sum_pred - sum_actual) / sum_actual
    mae        = float(predictions["residual"].abs().mean())

    print("\n--- Calibration ---")
    print(f"Sum predicted (expected_total):  {sum_pred:.1f}")
    print(f"Sum actual   (actual_total):     {sum_actual}")
    print(f"Difference:                      {pct_diff:+.1f}%  "
          f"({'OK' if abs(pct_diff) <= 10 else 'WARNING: >10% gap flags misspecification'})")
    print(f"Mean absolute error:             {mae:.2f} crashes per intersection (2018–2023)")

    # Top residuals
    for label, method in (
        ("POSITIVE — actual >> predicted ('worse than it looks')", "nlargest"),
        ("NEGATIVE — predicted >> actual ('safer than predicted')", "nsmallest"),
    ):
        top = getattr(predictions, method)(10, "residual")
        print(f"\nTop 10 {label}:")
        print(
            top[["intersection_id", "actual_total", "expected_total", "residual"]]
            .round({"expected_total": 2, "residual": 2})
            .to_string(index=False)
        )

    # Exposure-proxy coefficient annotation (is_arterial dropped — see FORMULA comment)
    proxy_cols = [
        p for p in result.params.index
        if p == "max_speed_limit" or p.startswith("C(arterial_class)")
    ]
    print(
        "\n--- Exposure-proxy coefficients ---\n"
        "(Expected to be inflated because they absorb the missing AADT signal;\n"
        " do not interpret as pure infrastructure effects — see AADT caveat above.)"
    )
    print(result.params[proxy_cols].round(4).to_string())

    # 5. Write
    write_outputs(result, predictions)
    print(f"\nWrote predictions  → {PREDICTIONS_PATH}")
    print(f"Saved model        → {MODEL_PATH}")
