"""
Combine model-expected crash baseline with observed VLM near-miss event rates
into a single percentile-based risk score for each Capitol Hill intersection.

Design rationale
----------------
The underlying NB model (nb_v1_no_aadt) ranks intersections well but does NOT
produce calibrated absolute crash counts — the AADT exposure term is missing.
Therefore the frontend score is PERCENTILE / RANK based. Raw
expected_crashes_per_year is carried as a secondary field for the drill-in
panel but must be treated as uncalibrated.

Empirical Bayes (EB) adjustment (AASHTO HSM Part C)
----------------------------------------------------
Before percentile ranking, model predictions are EB-adjusted:
    w  = 1 / (1 + alpha * predicted)      # weight toward the model
    eb = w * predicted + (1 - w) * observed
This pulls extreme over-predictions toward the observed count without
discarding the model entirely. It corrects the main failure of the raw
ranking (intersections the model over-predicts by 10× rank #1) while
preserving signal at low-observation sites where the observed count alone
would be too noisy. Alpha = 0.6788 from the fitted NB dispersion parameter.

NOTE — (observed - expected) / sqrt(expected) residual scoring is explicitly
NOT used here. That formula assumes a Poisson residual distribution and a
shared measurement process, but (a) crashes and VLM near-misses are different
physical processes with different detection rates, and (b) the model is NB,
not Poisson. Percentile blending of the EB estimate is the MVP approach.

Inputs
------
data/intermediate/intersection_predictions.parquet  — built by fit_risk_model.py
data/intermediate/vlm_events_by_intersection.parquet — teammate output, optional

Output
------
data/intermediate/intersection_scores.parquet
    651 rows: intersection_id, risk_score (PRIMARY, 0–100), risk_rank,
    risk_tier, expected_percentile, observed_percentile, has_vlm_data,
    expected_crashes_per_year (SECONDARY — uncalibrated), model_version,
    scored_at

Run after : python pipeline/fit_risk_model.py
Run before: export_to_supabase.py (day-7 migration)
"""

import pickle
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
PREDICTIONS_PATH = ROOT / "data" / "intermediate" / "intersection_predictions.parquet"
VLM_PATH         = ROOT / "data" / "intermediate" / "vlm_events_by_intersection.parquet"
OUT_PATH         = ROOT / "data" / "intermediate" / "intersection_scores.parquet"
MODEL_PATH       = ROOT / "data" / "model" / "nb_v1_no_aadt.pkl"

# EB dispersion parameter from the fitted nb_v1_no_aadt summary.
# Used as fallback when the pkl does not expose alpha programmatically.
ALPHA_HARDCODED = 0.6788

YEARS_OBSERVED = 6  # 2018–2023 inclusive

# Risk tier cut-points on the 0–100 risk_score scale.
# These are quintile boundaries, so when scoring is purely expected-percentile
# (uniform distribution) each tier contains ~130 of 651 intersections.
#   very_high : risk_score >= 80   (top 20%)
#   high      : 60 <= score < 80
#   moderate  : 40 <= score < 60
#   low       : 20 <= score < 40
#   very_low  : score < 20        (bottom 20%)
TIER_CUTS = [(80, "very_high"), (60, "high"), (40, "moderate"), (20, "low")]


def _percentile_rank(series: pd.Series) -> pd.Series:
    """
    Return percentile rank (0–100) for non-null values in series.
    Null values stay null. Uses average method so ties get the same rank.
    """
    return series.rank(pct=True, method="average", na_option="keep") * 100


def _assign_tier(score: float) -> str:
    for cut, label in TIER_CUTS:
        if score >= cut:
            return label
    return "very_low"


def _load_alpha() -> tuple[float, str]:
    """
    Try to recover the NB dispersion parameter alpha from the saved model pkl.
    Returns (alpha, source) where source is 'pkl' or 'hardcoded'.
    Falls back to ALPHA_HARDCODED if the file is absent or alpha is not
    accessible as a named attribute/param.
    """
    if MODEL_PATH.exists():
        try:
            with open(MODEL_PATH, "rb") as f:
                result = pickle.load(f)
            alpha: Optional[float] = None
            if hasattr(result, "params") and "alpha" in getattr(result.params, "index", []):
                alpha = float(result.params["alpha"])
            elif hasattr(result, "alpha"):
                alpha = float(result.alpha)
            if alpha is not None and alpha > 0:
                return alpha, "pkl"
        except Exception:
            pass
    return ALPHA_HARDCODED, f"hardcoded ({ALPHA_HARDCODED}) — from nb_v1_no_aadt summary"


# ---------------------------------------------------------------------------
# EB adjustment
# ---------------------------------------------------------------------------

def compute_eb_estimate(
    predictions: pd.DataFrame,
    alpha: float,
) -> pd.DataFrame:
    """
    Apply AASHTO HSM Part C Empirical Bayes site estimation.

    For each intersection:
      w  = 1 / (1 + alpha * predicted)   # EB weight toward model; NB form
      eb = w * predicted + (1 - w) * observed

    where predicted = expected_total (6-yr model output) and
    observed = actual_total (observed crashes over the same window).

    EB pulls extreme over-predictions toward the observed count, correcting
    for regression-to-the-mean without discarding the model entirely.

    Returns a DataFrame with:
      intersection_id, eb_estimate (6-yr window), eb_estimate_per_year
    """
    df = predictions[["intersection_id", "expected_total", "actual_total"]].copy()

    # Guard: negative or null predicted values should not exist after the
    # prediction fix in fit_risk_model.py — stop here rather than propagate NaN.
    bad = df["expected_total"].isna() | (df["expected_total"] < 0)
    if bad.any():
        sys.exit(
            f"[ERROR] {bad.sum()} rows have null or negative expected_total. "
            "Re-run: python pipeline/fit_risk_model.py"
        )

    predicted = df["expected_total"]
    observed  = df["actual_total"].astype(float)

    w  = 1.0 / (1.0 + alpha * predicted)
    eb = w * predicted + (1.0 - w) * observed

    # EB result must be non-negative for a count model
    if (eb < 0).any():
        sys.exit(
            f"[ERROR] {(eb < 0).sum()} EB estimates are negative "
            f"(alpha={alpha}, check inputs)."
        )

    return pd.DataFrame({
        "intersection_id":      df["intersection_id"].values,
        "eb_estimate":          eb.values,
        "eb_estimate_per_year": (eb / YEARS_OBSERVED).values,
    })


# ---------------------------------------------------------------------------
# Load predictions (required)
# ---------------------------------------------------------------------------

def load_predictions() -> pd.DataFrame:
    """
    Load intersection_predictions.parquet.  Stops with a clear error if absent.
    """
    if not PREDICTIONS_PATH.exists():
        sys.exit(
            f"[ERROR] {PREDICTIONS_PATH} not found.\n"
            "Run:  python pipeline/fit_risk_model.py"
        )
    return pd.read_parquet(PREDICTIONS_PATH)


# ---------------------------------------------------------------------------
# Load VLM data (optional)
# ---------------------------------------------------------------------------

def load_vlm_optional() -> Optional[pd.DataFrame]:
    """
    Load vlm_events_by_intersection.parquet if it exists; return None if not.

    Expected columns: intersection_id, observed_events, observation_days.
    Rows with observation_days == 0 get observed_rate = NaN (no exposure).
    """
    if not VLM_PATH.exists():
        return None

    vlm = pd.read_parquet(VLM_PATH)
    vlm = vlm[["intersection_id", "observed_events", "observation_days"]].copy()

    # Guard against zero-division; set rate to NaN where there is no exposure
    zero_days = vlm["observation_days"] == 0
    vlm["observed_rate"] = vlm["observed_events"] / vlm["observation_days"].where(~zero_days)

    return vlm


# ---------------------------------------------------------------------------
# Compute scores
# ---------------------------------------------------------------------------

def compute_scores(
    predictions: pd.DataFrame,
    vlm: Optional[pd.DataFrame],
    alpha: float,
) -> pd.DataFrame:
    """
    Build the scored DataFrame with all 651 rows.

    Scoring:
      eb_estimate / eb_estimate_per_year
                           — EB-adjusted crash estimate (AASHTO HSM Part C);
                             computed from expected_total and actual_total via
                             compute_eb_estimate().
      expected_percentile  — percentile rank of eb_estimate_per_year across
                             all 651 intersections.  (Name kept for schema
                             compatibility; the basis is now EB, not raw model.)
      observed_percentile  — percentile rank of observed_rate (NaN if no VLM)
      risk_score           — mean(expected_percentile, observed_percentile)
                             when both present; expected_percentile alone
                             otherwise.  Equal weighting is a deliberate MVP
                             choice; weights are tunable once VLM is validated.
      risk_rank            — dense integer rank (1 = highest risk_score)
      risk_tier            — quintile label derived from risk_score cut-points
      has_vlm_data         — bool, True only for intersections with VLM rows
      expected_crashes_per_year — RAW pre-EB model output, secondary/drill-in only
    """
    df = predictions[
        ["intersection_id", "expected_crashes_per_year", "model_version"]
    ].copy()

    # 1. EB adjustment → use eb_estimate_per_year as the expected component
    eb = compute_eb_estimate(predictions, alpha)
    df = df.merge(eb, on="intersection_id", how="left")
    df["expected_percentile"] = _percentile_rank(df["eb_estimate_per_year"])

    # 2. Observed percentile (only when VLM data is present)
    df["observed_percentile"] = float("nan")
    df["has_vlm_data"]        = False

    if vlm is not None:
        df = df.merge(
            vlm[["intersection_id", "observed_rate"]],
            on="intersection_id",
            how="left",
        )
        has_vlm = df["observed_rate"].notna()
        df["has_vlm_data"] = has_vlm

        # Percentile rank computed only among intersections that have VLM data
        vlm_ranks = _percentile_rank(df.loc[has_vlm, "observed_rate"])
        df.loc[has_vlm, "observed_percentile"] = vlm_ranks.values

        df = df.drop(columns=["observed_rate"])

    # 3. Combined risk_score (equal-weight blend; observed_percentile NaN → skip)
    both_present = df["observed_percentile"].notna()
    df["risk_score"] = df["expected_percentile"]
    df.loc[both_present, "risk_score"] = (
        df.loc[both_present, "expected_percentile"]
        + df.loc[both_present, "observed_percentile"]
    ) / 2.0

    # 4. Dense rank: 1 = highest risk_score
    df["risk_rank"] = (
        df["risk_score"].rank(method="dense", ascending=False).astype(int)
    )

    # 5. Quintile tier
    df["risk_tier"] = df["risk_score"].apply(_assign_tier)

    # Column order: primary fields first; expected_crashes_per_year is secondary
    return df[[
        "intersection_id",
        "risk_score",
        "risk_rank",
        "risk_tier",
        "expected_percentile",
        "observed_percentile",
        "eb_estimate",
        "eb_estimate_per_year",
        "expected_crashes_per_year",   # secondary — raw pre-EB, uncalibrated
        "has_vlm_data",
        "model_version",
    ]]


# ---------------------------------------------------------------------------
# Write output
# ---------------------------------------------------------------------------

def write_output(scores: pd.DataFrame) -> None:
    """Write scores to parquet, adding a scored_at timestamp."""
    out = scores.copy()
    out["scored_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    out.to_parquet(OUT_PATH, index=False)


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # 1. Load
    predictions = load_predictions()
    vlm         = load_vlm_optional()

    if vlm is None:
        print("[NOTICE] VLM data not yet available "
              f"({VLM_PATH.name} not found).\n"
              "         Scores will be based on the EB-adjusted expected component only.")
        n_vlm = 0
    else:
        n_vlm = int(vlm["intersection_id"].nunique())
        print(f"VLM data loaded: {n_vlm} of 651 intersections have observed events.")

    # 2. Alpha
    alpha, alpha_source = _load_alpha()
    print(f"\nAlpha (NB dispersion): {alpha}  [source: {alpha_source}]")

    # 3. Before/after table (computed before scoring to show rank shift)
    eb_for_table = compute_eb_estimate(predictions, alpha)
    ba = predictions[["intersection_id", "expected_total", "actual_total",
                       "expected_crashes_per_year"]].copy()
    ba = ba.merge(eb_for_table, on="intersection_id", how="left")
    ba["old_rank"] = (
        ba["expected_crashes_per_year"]
        .rank(method="dense", ascending=False).astype(int)
    )
    ba["new_rank"] = (
        ba["eb_estimate_per_year"]
        .rank(method="dense", ascending=False).astype(int)
    )
    ba["abs_gap"] = (ba["expected_total"] - ba["actual_total"]).abs()

    print("\n--- Before/After EB: top 10 intersections by |predicted - observed| ---")
    print(
        ba.nlargest(10, "abs_gap")[
            ["intersection_id", "expected_total", "actual_total",
             "eb_estimate", "old_rank", "new_rank"]
        ]
        .round({"expected_total": 1, "eb_estimate": 1})
        .rename(columns={"expected_total": "predicted", "actual_total": "observed"})
        .to_string(index=False)
    )

    # Specific intersection checks requested in the spec
    flagged = {
        "cdb875cde624": "over-predicted (expected #1 before EB; should move DOWN)",
        "712128e34142": "over-predicted (expected #2 before EB; should move DOWN)",
        "a932fcb41bb1": "high actual (40 crashes; should move UP)",
    }
    print("\n--- Specific intersection rank check ---")
    for iid, note in flagged.items():
        row = ba[ba["intersection_id"] == iid]
        if row.empty:
            print(f"  {iid}: NOT FOUND in predictions  ({note})")
        else:
            r = row.iloc[0]
            direction = "↓ DOWN" if r["new_rank"] > r["old_rank"] else "↑ UP"
            print(
                f"  {iid}  old_rank={int(r['old_rank']):>3}  "
                f"new_rank={int(r['new_rank']):>3}  {direction}   {note}"
            )

    # 4. Score
    scores = compute_scores(predictions, vlm, alpha)

    # 5. Sanity checks
    n_rows  = len(scores)
    n_dupes = int(scores["intersection_id"].duplicated().sum())
    print(f"\nOutput rows:          {n_rows}  (expect 651)")
    print(f"Duplicate ids:        {n_dupes}  (expect 0)")

    rs = scores["risk_score"]
    print(f"risk_score  min/med/max:  "
          f"{rs.min():.1f} / {rs.median():.1f} / {rs.max():.1f}")

    print("\nrisk_tier distribution (expect ~130 per tier if VLM absent):")
    tier_order = ["very_high", "high", "moderate", "low", "very_low"]
    tier_vc = scores["risk_tier"].value_counts().reindex(tier_order, fill_value=0)
    print(tier_vc.to_string())

    print("\nTop 15 intersections by risk_score:")
    cols = [
        "intersection_id", "risk_score", "risk_rank", "risk_tier",
        "eb_estimate_per_year", "expected_crashes_per_year", "has_vlm_data",
    ]
    print(
        scores.nlargest(15, "risk_score")[cols]
        .round({"risk_score": 1, "eb_estimate_per_year": 3,
                "expected_crashes_per_year": 3})
        .to_string(index=False)
    )

    print(
        "\n[REMINDER] risk_score is a RELATIVE RANK (0–100 percentile), NOT a "
        "calibrated crash count.\n"
        "           Primary ranking is EB-adjusted per AASHTO HSM Part C "
        f"(alpha={alpha}).\n"
        "           expected_crashes_per_year is the raw pre-EB model output "
        "for reference only (uncalibrated — no AADT)."
    )

    # 6. Write
    write_output(scores)
    print(f"\nWrote {n_rows} rows → {OUT_PATH}")
