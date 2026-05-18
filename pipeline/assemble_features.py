"""
Assemble the feature matrix for the Seattle intersection risk model.

Joins infrastructure data to the 651 Capitol Hill intersections to produce
one row per intersection with all predictors. NaNs are left in place — the
model script handles imputation. Inspect Step 0 output carefully: any
feature that joins to all-null or all-zero indicates a broken join.

Inputs
------
data/intermediate/intersections.parquet   — built by build_intersections.py
data/raw/streets.geojson                  — downloaded by seattle_arcgis.py
data/raw/traffic_signals.geojson          — downloaded by seattle_arcgis.py
data/raw/bike_facilities.geojson          — downloaded by seattle_arcgis.py
data/raw/aadt.geojson                     — optional; NaN column if absent

Output
------
data/intermediate/intersection_features.parquet
    651 rows × 8 columns: intersection_id, num_legs, is_signalized,
    max_speed_limit, is_arterial, arterial_class, bike_facility, max_aadt

Run after : python pipeline/build_intersections.py
Run before: python pipeline/fit_model.py
"""

import sys
from pathlib import Path
from typing import Optional

import geopandas as gpd
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
INTERSECTIONS_PATH = ROOT / "data" / "intermediate" / "intersections.parquet"
STREETS_PATH       = ROOT / "data" / "raw" / "streets.geojson"
SIGNALS_PATH       = ROOT / "data" / "raw" / "traffic_signals.geojson"
BIKE_PATH          = ROOT / "data" / "raw" / "bike_facilities.geojson"
AADT_PATH          = ROOT / "data" / "raw" / "aadt.geojson"
OUT_PATH           = ROOT / "data" / "intermediate" / "intersection_features.parquet"

UTM  = "EPSG:32610"
WGS84 = "EPSG:4326"

SIGNAL_SNAP_M = 25.0
BIKE_SNAP_M   = 15.0
AADT_SNAP_M   = 30.0


# ---------------------------------------------------------------------------
# Geometry normalizer (mirrors snap_crashes.py)
# ---------------------------------------------------------------------------

def _normalize_geometry(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Rename 'geom' → 'geometry' if needed and set it as active geometry."""
    if "geometry" not in gdf.columns and "geom" in gdf.columns:
        gdf = gdf.rename_geometry("geometry")
    return gdf.set_geometry("geometry")


# ---------------------------------------------------------------------------
# Load
# ---------------------------------------------------------------------------

def load_inputs() -> tuple[
    gpd.GeoDataFrame,
    gpd.GeoDataFrame,
    gpd.GeoDataFrame,
    gpd.GeoDataFrame,
    Optional[gpd.GeoDataFrame],
]:
    """
    Load and reproject all inputs to UTM.

    Returns (intersections, streets, signals, bike, aadt).
    aadt is None if the file is missing (caller prints warning and proceeds).
    Exits with a clear error for any other missing required file.
    """
    required = {
        "intersections": INTERSECTIONS_PATH,
        "streets":       STREETS_PATH,
        "signals":       SIGNALS_PATH,
        "bike":          BIKE_PATH,
    }
    missing = [
        f"  {p}  →  run: python pipeline/seattle_arcgis.py"
        for name, p in required.items()
        if not p.exists()
        and not (name == "intersections" and not p.exists())  # re-checked below
    ]
    # Separate check so the error message names the right producing script
    if not INTERSECTIONS_PATH.exists():
        missing.insert(
            0,
            f"  {INTERSECTIONS_PATH}  →  run: python pipeline/build_intersections.py",
        )
    for p in (STREETS_PATH, SIGNALS_PATH, BIKE_PATH):
        if not p.exists():
            missing.append(f"  {p}  →  run: python pipeline/seattle_arcgis.py")
    if missing:
        sys.exit("[ERROR] Missing required inputs:\n" + "\n".join(missing))

    def _load(path: Path) -> gpd.GeoDataFrame:
        if path.suffix == ".parquet":
            return _normalize_geometry(gpd.read_parquet(path)).to_crs(UTM)
        return _normalize_geometry(gpd.read_file(path)).to_crs(UTM)

    intersections = _load(INTERSECTIONS_PATH)
    streets       = _load(STREETS_PATH)
    signals       = _load(SIGNALS_PATH)
    bike          = _load(BIKE_PATH)

    aadt: Optional[gpd.GeoDataFrame] = None
    if AADT_PATH.exists():
        aadt = _load(AADT_PATH)

    return intersections, streets, signals, bike, aadt


# ---------------------------------------------------------------------------
# Step 0 — schema inspection (returns field names for downstream use)
# ---------------------------------------------------------------------------

def inspect_schema(
    streets: gpd.GeoDataFrame,
    signals: gpd.GeoDataFrame,
    bike: gpd.GeoDataFrame,
    aadt: Optional[gpd.GeoDataFrame],
) -> tuple[str, str, Optional[str], Optional[str]]:
    """
    Print column names, dtypes, first 3 non-geom rows, and key field
    distributions for every input layer.

    Returns (compkey_col, artclass_col, aadt_count_col, aadt_year_col).
    aadt cols are None when aadt is None.
    """
    def _head(gdf: gpd.GeoDataFrame, label: str) -> None:
        non_geom = gdf.drop(columns=gdf.geometry.name)
        print(f"\n=== {label} schema ===")
        print(non_geom.dtypes.to_string())
        print(f"\n--- {label}: first 3 rows ---")
        print(non_geom.head(3).to_string())

    _head(streets, "streets")

    # Locate COMPKEY (permanent street ID)
    if "COMPKEY" not in streets.columns:
        raise RuntimeError(
            "COMPKEY column missing from streets.geojson. "
            "Re-download via seattle_arcgis.py."
        )
    compkey_col = "COMPKEY"

    for field in ("SPEEDLIMIT", "ARTCLASS", "ARTDESCRIPT"):
        if field in streets.columns:
            print(f"\n--- streets '{field}' distribution ---")
            print(streets[field].value_counts(dropna=False).sort_index().to_string())
        else:
            print(f"\n[WARN] streets: '{field}' column not found.")

    _head(signals, "traffic_signals")
    _head(bike, "bike_facilities")

    # Locate ARTCLASS column (may be ARTCLASS or similar)
    artclass_candidates = [c for c in streets.columns if "artclass" in c.lower()]
    if not artclass_candidates:
        raise RuntimeError(
            "No ARTCLASS-like column found in streets.geojson. "
            "Inspect Step 0 output and update artclass_col manually."
        )
    artclass_col = artclass_candidates[0]

    # AADT schema
    aadt_count_col: Optional[str] = None
    aadt_year_col:  Optional[str] = None
    if aadt is not None:
        _head(aadt, "aadt")
        count_candidates = [
            c for c in aadt.columns
            if c.upper() in ("AADT", "COUNTAADT", "AADT_COUNT", "COUNT")
            or "aadt" in c.lower()
        ]
        year_candidates = [
            c for c in aadt.columns
            if "year" in c.lower() or c.upper() == "YEAR"
        ]
        if not count_candidates:
            print("[WARN] AADT: no count field found — aadt feature will be all-NaN.")
        else:
            aadt_count_col = count_candidates[0]
            print(f"\n[INFO] AADT count field: '{aadt_count_col}'")
        if not year_candidates:
            print("[WARN] AADT: no year field found — will use all rows (no year filter).")
        else:
            aadt_year_col = year_candidates[0]
            print(f"[INFO] AADT year field:  '{aadt_year_col}'")
            print(f"       year range: {aadt[aadt_year_col].min()} – {aadt[aadt_year_col].max()}")

    return compkey_col, artclass_col, aadt_count_col, aadt_year_col


# ---------------------------------------------------------------------------
# Feature functions (each takes the working features DataFrame + source layer,
# mutates nothing — returns a Series or DataFrame to merge in __main__)
# ---------------------------------------------------------------------------

def add_signal_feature(
    intersections: gpd.GeoDataFrame,
    signals: gpd.GeoDataFrame,
) -> pd.Series:
    """
    is_signalized (0/1): signal point within SIGNAL_SNAP_M of intersection.

    Uses sjoin_nearest; intersections with no signal within 25 m get 0.
    """
    joined = gpd.sjoin_nearest(
        intersections[["intersection_id", "geometry"]],
        signals[["geometry"]],
        how="left",
        max_distance=SIGNAL_SNAP_M,
        distance_col="_sig_dist",
    )
    signalized = joined.groupby("intersection_id")["_sig_dist"].min().notna()
    return signalized.astype(int).rename("is_signalized")


def add_speed_feature(
    intersections: gpd.GeoDataFrame,
    streets: gpd.GeoDataFrame,
    compkey_col: str,
) -> pd.Series:
    """
    max_speed_limit (float): max SPEEDLIMIT across connected streets (joined by COMPKEY).

    Stays NaN when all connected streets have null speed.
    """
    if "SPEEDLIMIT" not in streets.columns:
        return pd.Series(float("nan"), index=intersections["intersection_id"], name="max_speed_limit")

    speed_lookup = (
        streets[[compkey_col, "SPEEDLIMIT"]]
        .dropna(subset=["SPEEDLIMIT"])
        .set_index(compkey_col)["SPEEDLIMIT"]
        .to_dict()
    )

    def _max_speed(compkeys: list) -> float:
        speeds = [speed_lookup[k] for k in compkeys if k in speed_lookup]
        return max(speeds) if speeds else float("nan")

    result = intersections.set_index("intersection_id")["connected_street_ids"].apply(_max_speed)
    return result.rename("max_speed_limit")


def add_arterial_feature(
    intersections: gpd.GeoDataFrame,
    streets: gpd.GeoDataFrame,
    compkey_col: str,
    artclass_col: str,
) -> pd.DataFrame:
    """
    is_arterial (0/1) and arterial_class (int): derived from ARTCLASS on connected streets.

    ARTCLASS observed values (from Step 0):
      0 or null = non-arterial / local access
      1         = principal arterial
      2         = minor arterial
      3         = collector arterial
      4         = not-otherwise-classified arterial
    is_arterial = 1 when max ARTCLASS >= 1.
    arterial_class = max ARTCLASS (0 if all connected streets are 0/null).
    """
    class_lookup = (
        streets[[compkey_col, artclass_col]]
        .dropna(subset=[artclass_col])
        .set_index(compkey_col)[artclass_col]
        .to_dict()
    )

    def _max_class(compkeys: list) -> int:
        classes = [class_lookup[k] for k in compkeys if k in class_lookup]
        return int(max(classes)) if classes else 0

    arterial_class = (
        intersections.set_index("intersection_id")["connected_street_ids"]
        .apply(_max_class)
        .rename("arterial_class")
    )
    is_arterial = (arterial_class >= 1).astype(int).rename("is_arterial")
    return pd.DataFrame({"is_arterial": is_arterial, "arterial_class": arterial_class})


def add_bike_feature(
    intersections: gpd.GeoDataFrame,
    bike: gpd.GeoDataFrame,
) -> pd.Series:
    """
    bike_facility (0/1): any bike facility LineString within BIKE_SNAP_M of intersection.

    sjoin_nearest on the bike layer; intersections with nothing within 15 m get 0.
    """
    joined = gpd.sjoin_nearest(
        intersections[["intersection_id", "geometry"]],
        bike[["geometry"]],
        how="left",
        max_distance=BIKE_SNAP_M,
        distance_col="_bike_dist",
    )
    has_bike = joined.groupby("intersection_id")["_bike_dist"].min().notna()
    return has_bike.astype(int).rename("bike_facility")


def add_aadt_feature(
    intersections: gpd.GeoDataFrame,
    aadt: Optional[gpd.GeoDataFrame],
    aadt_count_col: Optional[str],
    aadt_year_col: Optional[str],
) -> pd.Series:
    """
    max_aadt (float): max AADT among segments within AADT_SNAP_M of intersection,
    using the most recent year available per segment.

    AADT geometry rarely aligns with COMPKEY, so we match spatially.
    All NaN when aadt is None or count field is missing.
    """
    nan_series = pd.Series(
        float("nan"),
        index=intersections["intersection_id"],
        name="max_aadt",
    )

    if aadt is None or aadt_count_col is None:
        return nan_series

    # Keep only the most recent year per geometry (row-level deduplicate)
    if aadt_year_col is not None:
        aadt = (
            aadt.sort_values(aadt_year_col, ascending=False)
            .drop_duplicates(subset=[aadt.geometry.name])
        )

    aadt_clean = aadt[[aadt_count_col, "geometry"]].dropna(subset=[aadt_count_col]).copy()
    aadt_clean[aadt_count_col] = pd.to_numeric(aadt_clean[aadt_count_col], errors="coerce")
    aadt_clean = aadt_clean.dropna(subset=[aadt_count_col])

    if aadt_clean.empty:
        return nan_series

    joined = gpd.sjoin_nearest(
        intersections[["intersection_id", "geometry"]],
        aadt_clean[["geometry", aadt_count_col]],
        how="left",
        max_distance=AADT_SNAP_M,
        distance_col="_aadt_dist",
    )
    max_aadt = joined.groupby("intersection_id")[aadt_count_col].max().rename("max_aadt")
    return max_aadt


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # 1. Load
    intersections, streets, signals, bike, aadt = load_inputs()
    if aadt is None:
        print(f"[WARN] {AADT_PATH} not found — max_aadt will be all-NaN.")

    # Step 0 — schema inspection
    print("\n" + "=" * 60)
    compkey_col, artclass_col, aadt_count_col, aadt_year_col = inspect_schema(
        streets, signals, bike, aadt
    )
    print("=" * 60 + "\n")

    # 2. Build feature table starting from intersections
    features = intersections[["intersection_id", "num_legs"]].copy()

    # is_signalized
    sig = add_signal_feature(intersections, signals)
    features = features.merge(sig.reset_index(), on="intersection_id", how="left")

    # max_speed_limit
    spd = add_speed_feature(intersections, streets, compkey_col)
    features = features.merge(spd.reset_index(), on="intersection_id", how="left")

    # is_arterial + arterial_class
    art = add_arterial_feature(intersections, streets, compkey_col, artclass_col)
    features = features.merge(art.reset_index(), on="intersection_id", how="left")

    # bike_facility
    bk = add_bike_feature(intersections, bike)
    features = features.merge(bk.reset_index(), on="intersection_id", how="left")

    # max_aadt
    aadt_feat = add_aadt_feature(intersections, aadt, aadt_count_col, aadt_year_col)
    features = features.merge(aadt_feat.reset_index(), on="intersection_id", how="left")

    # Cast binary cols to int (merge may introduce float via NaN expansion)
    for col in ("is_signalized", "is_arterial", "bike_facility"):
        features[col] = features[col].fillna(0).astype(int)
    features["arterial_class"] = features["arterial_class"].fillna(0).astype(int)

    # 3. Write
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    features.to_parquet(OUT_PATH, index=False)
    print(f"Wrote {len(features)} rows → {OUT_PATH}\n")

    # 4. Sanity / coverage report
    print("=== Feature coverage report ===")
    print(f"{'Column':<22} {'non-null':>8} {'null':>6}   summary")
    print("-" * 60)
    for col in ("num_legs", "is_signalized", "max_speed_limit",
                "is_arterial", "arterial_class", "bike_facility", "max_aadt"):
        s = features[col]
        n_nn = int(s.notna().sum())
        n_na = int(s.isna().sum())
        if col in ("is_signalized", "is_arterial", "bike_facility"):
            summary = f"0={int((s==0).sum())}  1={int((s==1).sum())}"
        elif col == "arterial_class":
            summary = f"max={int(s.max())}  vc below"
        else:
            summary = (
                f"min={s.min():.0f}  med={s.median():.0f}  max={s.max():.0f}"
                if n_nn else "all NaN"
            )
        print(f"  {col:<20} {n_nn:>8} {n_na:>6}   {summary}")

    print(f"\nis_signalized == 1: {int((features['is_signalized']==1).sum())} "
          f"of {len(features)}  (expect ~10–25% if signal join is working)")
    print(f"non-null max_speed_limit: {int(features['max_speed_limit'].notna().sum())} "
          f"of {len(features)}  (expect near 651; gaps = broken COMPKEY join)")
    print(f"non-null max_aadt:        {int(features['max_aadt'].notna().sum())} "
          f"of {len(features)}  (AADT is sparse; 20–50% is acceptable)")

    print("\narterial_class value_counts:")
    print(features["arterial_class"].value_counts().sort_index().to_string())

    print("\nFirst 5 rows:")
    print(features.head().to_string(index=False))
