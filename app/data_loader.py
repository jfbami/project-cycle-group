"""
Load and join the per-intersection parquet outputs into a single DataFrame
used by both the CLI explainer and the Streamlit app.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import geopandas as gpd
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "intermediate"

INTERSECTIONS_PATH = DATA / "intersections.parquet"
FEATURES_PATH      = DATA / "intersection_features.parquet"
PREDICTIONS_PATH   = DATA / "intersection_predictions.parquet"
SCORES_PATH        = DATA / "intersection_scores.parquet"


@lru_cache(maxsize=1)
def load_joined() -> pd.DataFrame:
    """Inner-join scores ⨝ predictions ⨝ features ⨝ intersections on intersection_id.

    Returns a plain pandas DataFrame with lat/lon extracted from the WGS-84 geometry
    so it can feed pydeck directly.
    """
    missing = [p for p in (INTERSECTIONS_PATH, FEATURES_PATH, PREDICTIONS_PATH, SCORES_PATH)
               if not p.exists()]
    if missing:
        msg = "\n  ".join(str(p) for p in missing)
        raise FileNotFoundError(
            f"Pipeline output not found:\n  {msg}\n"
            "Run the pipeline first:\n"
            "  python seattle_arcgis.py\n"
            "  python pipeline/build_intersections.py\n"
            "  python pipeline/snap_crashes.py\n"
            "  python pipeline/assemble_features.py\n"
            "  python pipeline/fit_risk_model.py\n"
            "  python pipeline/score_risk.py"
        )

    inter = gpd.read_parquet(INTERSECTIONS_PATH)
    geom_col = "geom" if "geom" in inter.columns else "geometry"
    inter = inter.set_geometry(geom_col)
    inter["lon"] = inter[geom_col].x
    inter["lat"] = inter[geom_col].y
    inter = pd.DataFrame(inter.drop(columns=[geom_col, "connected_street_ids"], errors="ignore"))

    feats = pd.read_parquet(FEATURES_PATH).drop(columns=["num_legs"], errors="ignore")
    preds = pd.read_parquet(PREDICTIONS_PATH)[
        ["intersection_id", "expected_total", "actual_total", "residual"]
    ]
    scores = pd.read_parquet(SCORES_PATH)

    return (
        inter
        .merge(feats,  on="intersection_id", how="inner")
        .merge(preds,  on="intersection_id", how="inner")
        .merge(scores, on="intersection_id", how="inner")
    )


def get_intersection(intersection_id: str) -> dict:
    """Return one intersection row as a dict; raise KeyError if not found."""
    df = load_joined()
    row = df[df["intersection_id"] == intersection_id]
    if row.empty:
        raise KeyError(f"intersection_id {intersection_id!r} not found")
    return row.iloc[0].to_dict()


def sample_ids_by_tier(n_per_tier: int = 1) -> dict[str, list[str]]:
    """Pick a few IDs per risk_tier for quick prompt-iteration testing."""
    df = load_joined()
    return {
        tier: df.loc[df["risk_tier"] == tier, "intersection_id"].head(n_per_tier).tolist()
        for tier in ("very_high", "high", "moderate", "low", "very_low")
    }


if __name__ == "__main__":
    df = load_joined()
    print(f"Loaded {len(df)} intersections")
    print("\nColumns:", list(df.columns))
    print("\nTier distribution:")
    print(df["risk_tier"].value_counts().to_string())
    print("\nSample IDs per tier:")
    for tier, ids in sample_ids_by_tier(n_per_tier=2).items():
        print(f"  {tier:10s} {ids}")
