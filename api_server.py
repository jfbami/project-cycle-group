"""
FastAPI bridge: reads pipeline parquet output → serves GeoJSON for the Next.js frontend.

GET /api/intersections      →  GeoJSON FeatureCollection (651 intersection points)
GET /api/bike-facilities    →  GeoJSON FeatureCollection (bike lane lines)
GET /health                 →  {"status": "ok"}

Run the full pipeline first:
    python pipeline/build_intersections.py
    python pipeline/assemble_features.py
    python pipeline/snap_crashes.py
    python pipeline/fit_risk_model.py
    python pipeline/score_risk.py

Then start this server:
    uvicorn api_server:app --port 8000 --reload
"""

import json
from pathlib import Path

import geopandas as gpd
import pandas as pd
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data" / "intermediate"

ARTERIAL_LABELS = {
    0: "Local / Non-arterial",
    1: "Principal Arterial",
    2: "Minor Arterial",
    3: "Collector Arterial",
    4: "Other Arterial",
}

app = FastAPI(title="Capitol Hill Vision Zero API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_methods=["GET"],
    allow_headers=["*"],
)


def _load_geojson() -> dict:
    """Merge all pipeline parquet files and return a GeoJSON dict."""

    # ── 1. Geometry ──────────────────────────────────────────────────────────
    intersections: gpd.GeoDataFrame = gpd.read_parquet(DATA / "intersections.parquet")
    if "geom" in intersections.columns and "geometry" not in intersections.columns:
        intersections = intersections.rename_geometry("geometry")
    intersections = intersections.to_crs("EPSG:4326")

    # ── 2. Risk scores (risk_score, risk_tier, eb_estimate, severity cols) ───
    scores = pd.read_parquet(DATA / "intersection_scores.parquet")

    # ── 3. Infrastructure features ───────────────────────────────────────────
    features = pd.read_parquet(DATA / "intersection_features.parquet")

    # ── 4. Observed / predicted crash counts ─────────────────────────────────
    predictions = pd.read_parquet(DATA / "intersection_predictions.parquet")
    keep_pred = [c for c in ("intersection_id", "actual_total", "expected_total")
                 if c in predictions.columns]
    predictions = predictions[keep_pred]

    # ── 5. Merge everything ──────────────────────────────────────────────────
    df = (
        intersections
        .merge(scores,                                          on="intersection_id", how="left")
        .merge(features.drop(columns=["num_legs"], errors="ignore"), on="intersection_id", how="left")
        .merge(predictions,                                    on="intersection_id", how="left")
    )

    # ── 6. Rename columns to match frontend snake_case schema ────────────────
    df = df.rename(columns={
        "actual_total":   "observed_crashes",
        "expected_total": "predicted_crashes",
        "eb_estimate":    "eb_predicted",
    })

    # ── 7. Derive human-readable fields ──────────────────────────────────────
    # Intersection name from coordinates
    df["name"] = df.apply(
        lambda r: f"{r.geometry.y:.4f}°N, {abs(r.geometry.x):.4f}°W", axis=1
    )

    # Observation window (6 years: 2018-2023)
    df["years_observed"] = 6

    # bike_facility: 0/1 int → descriptive string
    if "bike_facility" in df.columns:
        df["bike_facility"] = df["bike_facility"].apply(
            lambda v: "None" if pd.isna(v) or int(v) == 0 else "Bike lane"
        )
    else:
        df["bike_facility"] = "None"

    # arterial_class: int → label string
    if "arterial_class" in df.columns:
        df["arterial_class"] = (
            df["arterial_class"]
            .fillna(0)
            .astype(int)
            .map(ARTERIAL_LABELS)
            .fillna("Other Arterial")
        )
    else:
        df["arterial_class"] = "Local / Non-arterial"

    # ── 8. Fill nulls so the frontend never gets NaN ─────────────────────────
    numeric_defaults = {
        "risk_score":       0.0,
        "predicted_crashes": 0.0,
        "eb_predicted":     0.0,
        "observed_crashes": 0.0,
        "injury_total":     0,
        "ksi_total":        0,
        "fatal_total":      0,
        "ped_total":        0,
        "bike_total":       0,
        "max_speed_limit":  0,
        "num_legs":         4,
        "is_signalized":    0,
    }
    for col, default in numeric_defaults.items():
        if col in df.columns:
            df[col] = df[col].fillna(default)

    df["risk_tier"] = df["risk_tier"].fillna("very_low")
    df["bike_facility"] = df["bike_facility"].fillna("None")

    # ── 9. Drop heavy / internal columns before serialising ──────────────────
    drop_cols = [c for c in ("connected_street_ids", "model_version",
                              "scored_at", "fitted_at", "residual",
                              "expected_percentile", "eb_estimate_per_year",
                              "expected_crashes_per_year", "is_arterial",
                              "max_aadt", "risk_rank") if c in df.columns]
    df = df.drop(columns=drop_cols)

    return json.loads(df.to_json())


@app.get("/api/intersections")
def get_intersections():
    try:
        return _load_geojson()
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=503,
            detail=(
                f"Pipeline output not found: {exc}. "
                "Run the full pipeline (build_intersections → assemble_features → "
                "snap_crashes → fit_risk_model → score_risk) then restart this server."
            ),
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/api/bike-facilities")
def get_bike_facilities():
    path = ROOT / "data" / "raw" / "bike_facilities.geojson"
    if not path.exists():
        raise HTTPException(status_code=503, detail="bike_facilities.geojson not found. Run seattle_arcgis.py first.")
    try:
        gdf = gpd.read_file(path).to_crs("EPSG:4326")
        # Keep only line geometries and a minimal set of properties
        gdf = gdf[gdf.geometry.geom_type.isin(["LineString", "MultiLineString"])].copy()
        keep = [c for c in ("BIKEFACILITY", "FACILITYTYPE", "STREETNAME", "geometry") if c in gdf.columns]
        return json.loads(gdf[keep].to_json())
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/health")
def health():
    return {"status": "ok"}
