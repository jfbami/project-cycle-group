"""
EB-adjust model predictions and emit a percentile-based risk score per
Capitol Hill intersection.

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
ranking (intersections the model over-predicts by 10x ranking #1) while
preserving signal at low-observation sites where the observed count alone
would be too noisy. Alpha is recovered from the fitted NB dispersion, with
ALPHA_HARDCODED as a fallback when the pkl cannot expose it.

NOTE — an earlier draft of this pipeline blended a VLM-detected near-miss
percentile into the score via an optional vlm_events_by_intersection.parquet
load. That branch has been removed: the data was never collected, the EB-only
ranking is the production behavior, and the VLM column is no longer in the
output schema.

Inputs
------
data/intermediate/intersection_predictions.parquet  — built by fit_risk_model.py

Output
------
data/intermediate/intersection_scores.parquet
    651 rows: intersection_id, risk_score (PRIMARY, 0-100), risk_rank,
    risk_tier, expected_percentile, eb_estimate, eb_estimate_per_year,
    expected_crashes_per_year (SECONDARY — uncalibrated), model_version,
    scored_at

Run after : python pipeline/fit_risk_model.py
"""

import pickle
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
PREDICTIONS_PATH = ROOT / "data" / "intermediate" / "intersection_predictions.parquet"
OUT_PATH         = ROOT / "data" / "intermediate" / "intersection_scores.parquet"
MODEL_PATH       = ROOT / "data" / "model" / "nb_v1_no_aadt.pkl"

# Fallback NB dispersion. Used only when the pkl cannot expose alpha
# programmatically; the actual fit usually yields ~0.65-0.80.
ALPHA_HARDCODED = 0.6788

YEARS_OBSERVED = 6  # 2018-2023 inclusive

# Risk tier cut-points on the 0-100 risk_score scale.
# very_high is intentionally narrowed to the top ~10% so it reads as severe
# rather than as "anywhere above average". The rest are not equal-width.
#   very_high : risk_score >= 90   (top ~10%)
#   high      : 70 <= score < 90   (next ~20%)
#   moderate  : 40 <= score < 70   (middle ~30%)
#   low       : 20 <= score < 40   (next ~20%)
#   very_low  : score < 20         (bottom ~20%)
TIER_CUTS = [(90, "very_high"), (70, "high"), (40, "moderate"), (20, "low")]


def _percentile_rank(series: pd.Series) -> pd.Series:
    """Percentile rank (0-100). Null values stay null."""
    return series.rank(pct=True, method="average", na_option="keep") * 100


def _assign_tier(score: float) -> str:
    for cut, label in TIER_CUTS:
        if score >= cut:
            return label
    return "very_low"


def _load_alpha() -> tuple[float, str]:
    """Recover NB dispersion alpha from the saved pkl; fall back to constant."""
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
    return ALPHA_HARDCODED, f"hardcoded ({ALPHA_HARDCODED}) - from nb_v1_no_aadt summary"


def compute_eb_estimate(predictions: pd.DataFrame, alpha: float) -> pd.DataFrame:
    """AASHTO HSM Part C Empirical Bayes site estimation.

      w  = 1 / (1 + alpha * predicted)
      eb = w * predicted + (1 - w) * observed
    """
    df = predictions[["intersection_id", "expected_total", "actual_total"]].copy()

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

    if (eb < 0).any():
        sys.exit(f"[ERROR] {(eb < 0).sum()} EB estimates are negative (alpha={alpha}).")

    return pd.DataFrame({
        "intersection_id":      df["intersection_id"].values,
        "eb_estimate":          eb.values,
        "eb_estimate_per_year": (eb / YEARS_OBSERVED).values,
    })


def load_predictions() -> pd.DataFrame:
    if not PREDICTIONS_PATH.exists():
        sys.exit(
            f"[ERROR] {PREDICTIONS_PATH} not found.\n"
            "Run:  python pipeline/fit_risk_model.py"
        )
    return pd.read_parquet(PREDICTIONS_PATH)


def compute_scores(predictions: pd.DataFrame, alpha: float) -> pd.DataFrame:
    """Build the scored DataFrame for all 651 intersections.

    Scoring:
      eb_estimate / eb_estimate_per_year   - EB-adjusted crash estimate.
      expected_percentile                  - percentile rank of eb_estimate_per_year.
      risk_score                           - = expected_percentile.
      risk_rank                            - dense integer rank (1 = highest).
      risk_tier                            - quintile label.
      expected_crashes_per_year            - RAW pre-EB, secondary/drill-in only.
    """
    df = predictions[["intersection_id", "expected_crashes_per_year", "model_version"]].copy()

    eb = compute_eb_estimate(predictions, alpha)
    df = df.merge(eb, on="intersection_id", how="left")
    df["expected_percentile"] = _percentile_rank(df["eb_estimate_per_year"])
    df["risk_score"] = df["expected_percentile"]
    df["risk_rank"]  = df["risk_score"].rank(method="dense", ascending=False).astype(int)
    df["risk_tier"]  = df["risk_score"].apply(_assign_tier)

    return df[[
        "intersection_id",
        "risk_score",
        "risk_rank",
        "risk_tier",
        "expected_percentile",
        "eb_estimate",
        "eb_estimate_per_year",
        "expected_crashes_per_year",   # secondary - raw pre-EB, uncalibrated
        "model_version",
    ]]


def write_output(scores: pd.DataFrame) -> None:
    out = scores.copy()
    out["scored_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    out.to_parquet(OUT_PATH, index=False)


if __name__ == "__main__":
    predictions = load_predictions()

    alpha, alpha_source = _load_alpha()
    print(f"Alpha (NB dispersion): {alpha}  [source: {alpha_source}]")

    # Before/after table — shows how EB shifts ranks for the most over/under-predicted sites.
    eb_for_table = compute_eb_estimate(predictions, alpha)
    ba = predictions[["intersection_id", "expected_total", "actual_total",
                       "expected_crashes_per_year"]].copy()
    ba = ba.merge(eb_for_table, on="intersection_id", how="left")
    ba["old_rank"] = ba["expected_crashes_per_year"].rank(method="dense", ascending=False).astype(int)
    ba["new_rank"] = ba["eb_estimate_per_year"].rank(method="dense", ascending=False).astype(int)
    ba["abs_gap"]  = (ba["expected_total"] - ba["actual_total"]).abs()

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

    scores = compute_scores(predictions, alpha)

    n_rows  = len(scores)
    n_dupes = int(scores["intersection_id"].duplicated().sum())
    print(f"\nOutput rows:          {n_rows}  (expect 651)")
    print(f"Duplicate ids:        {n_dupes}  (expect 0)")

    rs = scores["risk_score"]
    print(f"risk_score  min/med/max:  {rs.min():.1f} / {rs.median():.1f} / {rs.max():.1f}")

    print("\nrisk_tier distribution (very_high ~10%, high ~20%, moderate ~30%, low ~20%, very_low ~20%):")
    tier_order = ["very_high", "high", "moderate", "low", "very_low"]
    tier_vc = scores["risk_tier"].value_counts().reindex(tier_order, fill_value=0)
    print(tier_vc.to_string())

    print("\nTop 15 intersections by risk_score:")
    cols = [
        "intersection_id", "risk_score", "risk_rank", "risk_tier",
        "eb_estimate_per_year", "expected_crashes_per_year",
    ]
    print(
        scores.nlargest(15, "risk_score")[cols]
        .round({"risk_score": 1, "eb_estimate_per_year": 3, "expected_crashes_per_year": 3})
        .to_string(index=False)
    )

    print(
        "\n[REMINDER] risk_score is a RELATIVE RANK (0-100 percentile), NOT a "
        "calibrated crash count.\n"
        "           Primary ranking is EB-adjusted per AASHTO HSM Part C "
        f"(alpha={alpha}).\n"
        "           expected_crashes_per_year is the raw pre-EB model output "
        "for reference only (uncalibrated - no AADT)."
    )

    write_output(scores)
    print(f"\nWrote {n_rows} rows -> {OUT_PATH}")
