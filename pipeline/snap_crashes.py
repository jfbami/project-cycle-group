"""
Snap SDOT collision records to Capitol Hill intersections and produce the
target variable for the Negative Binomial crash-frequency model.

Inputs
------
data/intermediate/intersections.parquet  — built by build_intersections.py
data/raw/collisions.geojson              — downloaded by seattle_arcgis.py

Outputs
-------
data/intermediate/crashes_by_intersection_year.parquet
    One row per (intersection_id, year) for every intersection × 2018-2023.
    Zero-crash rows are included — they are required training data.

data/intermediate/crashes_by_intersection.parquet
    One row per intersection with total_crashes and years_observed.

Run after : python pipeline/build_intersections.py
Run before: python pipeline/assemble_features.py
"""

import sys
from pathlib import Path

import geopandas as gpd
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
INTERSECTIONS_PATH = ROOT / "data" / "intermediate" / "intersections.parquet"
COLLISIONS_PATH    = ROOT / "data" / "raw" / "collisions.geojson"
OUT_DIR            = ROOT / "data" / "intermediate"

UTM   = "EPSG:32610"
WGS84 = "EPSG:4326"

YEAR_MIN = 2018
YEAR_MAX = 2023
SNAP_DISTANCE_M = 25.0


# ---------------------------------------------------------------------------
# Load
# ---------------------------------------------------------------------------

def _normalize_geometry(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """
    Ensure the active geometry column is named 'geometry'.

    build_intersections.py writes its geometry as 'geom'; geopandas'
    sjoin_nearest requires both frames to expose their geometry via the
    standard name so column slicing like gdf[['geometry', ...]] works.
    """
    if "geometry" not in gdf.columns and "geom" in gdf.columns:
        gdf = gdf.rename_geometry("geometry")
    return gdf.set_geometry("geometry")


def load_inputs() -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame]:
    """Load intersections and collisions; normalize geometry column; reproject both to UTM."""
    missing = []
    if not INTERSECTIONS_PATH.exists():
        missing.append(
            f"  {INTERSECTIONS_PATH}  →  run: python pipeline/build_intersections.py"
        )
    if not COLLISIONS_PATH.exists():
        missing.append(
            f"  {COLLISIONS_PATH}  →  run: python pipeline/seattle_arcgis.py"
        )
    if missing:
        sys.exit("[ERROR] Missing required inputs:\n" + "\n".join(missing))

    intersections = _normalize_geometry(gpd.read_parquet(INTERSECTIONS_PATH)).to_crs(UTM)
    collisions    = _normalize_geometry(gpd.read_file(COLLISIONS_PATH)).to_crs(UTM)
    return intersections, collisions


# ---------------------------------------------------------------------------
# Schema inspection (prints in __main__, returns info for later use)
# ---------------------------------------------------------------------------

def inspect_collisions_schema(
    collisions: gpd.GeoDataFrame,
) -> tuple[str, str]:
    """
    Print column names, dtypes, first 3 non-geometry rows, and unique values
    of junction-type and severity fields.

    Returns (junction_col, date_col) after finding them by name heuristic.
    Raises RuntimeError if either cannot be identified.
    """
    non_geom = collisions.drop(columns=collisions.geometry.name)
    print("=== Collisions schema ===")
    print(non_geom.dtypes.to_string())
    print("\n--- First 3 rows ---")
    print(non_geom.head(3).to_string())

    # Locate junction-type field
    junction_candidates = [
        c for c in collisions.columns
        if "junction" in c.lower()
    ]
    if not junction_candidates:
        raise RuntimeError(
            "No junction-type column found in collisions. "
            "Cannot filter intersection-related crashes — stopping."
        )
    junction_col = junction_candidates[0]
    print(f"\n--- Junction field: '{junction_col}' unique values ---")
    print(collisions[junction_col].value_counts(dropna=False).to_string())

    # Locate severity field
    severity_candidates = [
        c for c in collisions.columns
        if "severity" in c.lower()
    ]
    severity_col = severity_candidates[0] if severity_candidates else None
    if severity_col:
        print(f"\n--- Severity field: '{severity_col}' unique values ---")
        print(collisions[severity_col].value_counts(dropna=False).to_string())
    else:
        print("\n[INFO] No severity field found (not needed for MVP).")

    # Prefer INCDTTM (human-readable string like "4/1/2013 5:30:00 PM").
    # INCDATE is int64 milliseconds since epoch — only use as fallback.
    if "INCDTTM" in collisions.columns:
        date_col = "INCDTTM"
    elif "INCDATE" in collisions.columns:
        date_col = "INCDATE"
    else:
        other = [c for c in collisions.columns if "date" in c.lower()]
        if not other:
            raise RuntimeError(
                "No date column found in collisions. Cannot filter by year — stopping."
            )
        date_col = other[0]
    print(f"\n[INFO] Using date column: '{date_col}', junction column: '{junction_col}'")

    return junction_col, date_col


# ---------------------------------------------------------------------------
# Filter crashes
# ---------------------------------------------------------------------------

JUNCTION_ALLOWLIST = frozenset({
    "At Intersection (intersection related)",
    "Mid-Block (but intersection related)",  # geocoded off-node but genuinely intersection crashes
})


def filter_crashes(
    collisions: gpd.GeoDataFrame,
    junction_col: str,
    date_col: str,
) -> tuple[gpd.GeoDataFrame, dict]:
    """
    Pipeline: parse dates → junction allowlist → date-range filter.

    Order matters: the junction null guard runs on RAW data so a broken
    date parse can never masquerade as a missing junction field.

    Returns (filtered_gdf, stats) where stats carries intermediate counts
    and date-range info for the caller to print.
    """
    df = collisions.copy()

    # Guard on RAW data — before any filtering
    if df[junction_col].isna().all():
        sys.exit(
            f"[ERROR] Junction field '{junction_col}' is entirely null in the raw "
            "collisions layer. Cannot identify intersection crashes — stopping."
        )

    # Parse dates: INCDTTM is a string; INCDATE is int64 milliseconds since epoch
    if date_col == "INCDATE":
        parsed = pd.to_datetime(df[date_col], unit="ms", errors="coerce")
    else:
        parsed = pd.to_datetime(df[date_col], errors="coerce")

    df["_year"] = parsed.dt.year
    nat_count    = int(parsed.isna().sum())
    valid_years  = df["_year"].dropna()
    year_min_obs = int(valid_years.min()) if len(valid_years) else None
    year_max_obs = int(valid_years.max()) if len(valid_years) else None

    # Exact junction allowlist — substring/contains would wrongly keep
    # "At Intersection (but not related to intersection)"
    df = df[df[junction_col].isin(JUNCTION_ALLOWLIST)].copy()
    n_after_junction = len(df)

    # Date-range filter last
    df = df[df["_year"].between(YEAR_MIN, YEAR_MAX)].copy()
    n_after_date = len(df)

    stats = {
        "nat_count":        nat_count,
        "year_min_obs":     year_min_obs,
        "year_max_obs":     year_max_obs,
        "n_after_junction": n_after_junction,
        "n_after_date":     n_after_date,
    }
    return df, stats


# ---------------------------------------------------------------------------
# Snap to intersections
# ---------------------------------------------------------------------------

# Severity fields carried from the raw collisions layer through the snap.
#
# Schema notes — SDOT changed how crash modality is encoded around 2018:
#   - MAXSEVERITYCODE (1=PDO, 2=Injury, 3=Serious, 4=Fatal): reliable across
#     the whole date range; the Vision Zero KSI counts are derived from it.
#   - PEDCOUNT / PEDCYLCOUNT (per-crash counts): populated pre-2018, mostly
#     null post-2018. Querying these alone undercounts ped/bike crashes 2018+.
#   - SDOT_COLDESC (free-text): populated across the whole range. Post-2018
#     ped/bike crashes are encoded only here, with terms "PEDESTRIAN" and
#     "PEDALCYCLIST" (SDOT's spelling for cyclist). Parsed below as a
#     fallback so the ped/bike counts are honest for both eras.
SEVERITY_COLS = ("MAXSEVERITYCODE", "PEDCOUNT", "PEDCYLCOUNT", "SDOT_COLDESC")


def snap_to_intersections(
    collisions: gpd.GeoDataFrame,
    intersections: gpd.GeoDataFrame,
) -> gpd.GeoDataFrame:
    """
    Spatial join each crash to its nearest intersection within SNAP_DISTANCE_M.

    Carries _year plus the per-crash severity fields (SERIOUSINJURIES, FATALITIES,
    PEDCOUNT, PEDCYLCOUNT) through so build_target_tables() can aggregate them
    per intersection for the Vision Zero scorecard.

    Crashes with no intersection within 25 m are dropped (counted by caller).
    """
    for label, gdf in (("collisions", collisions), ("intersections", intersections)):
        crs = gdf.crs.to_epsg() if gdf.crs else None
        print(f"  CRS check — {label}: EPSG:{crs}")
        if crs != 32610:
            sys.exit(
                f"[ERROR] {label} CRS is EPSG:{crs}, expected EPSG:32610. "
                "Snap aborted — distances would be meaningless."
            )
        if gdf.geometry.is_empty.all():
            sys.exit(f"[ERROR] {label} active geometry column is entirely empty.")

    # Keep severity columns that exist on this dataset; missing ones become 0 downstream.
    keep = ["geometry", "_year"] + [c for c in SEVERITY_COLS if c in collisions.columns]
    snapped = gpd.sjoin_nearest(
        collisions[keep],
        intersections[["intersection_id", "geometry"]],
        how="left",
        max_distance=SNAP_DISTANCE_M,
        distance_col="_snap_dist",
    )
    return snapped


# ---------------------------------------------------------------------------
# Build output tables
# ---------------------------------------------------------------------------

def build_target_tables(
    snapped: gpd.GeoDataFrame,
    intersections: gpd.GeoDataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Build the complete intersection × year grid (zeros included) and the
    per-intersection summary table with severity sub-counts.

    Returns (crashes_by_year, crashes_by_intersection). The per-intersection
    table has: intersection_id, total_crashes, years_observed,
    serious_total, fatal_total, ped_total, bike_total.
    """
    matched = snapped.dropna(subset=["intersection_id"]).copy()
    matched["year"] = matched["_year"].astype(int)

    # Counts per (intersection_id, year)
    counts = (
        matched.groupby(["intersection_id", "year"])
        .size()
        .reset_index(name="crash_count")
    )

    # Complete grid: every intersection × every year
    all_ids   = intersections["intersection_id"].unique()
    all_years = list(range(YEAR_MIN, YEAR_MAX + 1))
    grid = pd.MultiIndex.from_product(
        [all_ids, all_years], names=["intersection_id", "year"]
    ).to_frame(index=False)

    crashes_by_year = grid.merge(counts, on=["intersection_id", "year"], how="left")
    crashes_by_year["crash_count"] = crashes_by_year["crash_count"].fillna(0).astype(int)

    # Per-intersection summary
    years_observed = YEAR_MAX - YEAR_MIN + 1
    crashes_by_intersection = (
        crashes_by_year.groupby("intersection_id")["crash_count"]
        .sum()
        .reset_index(name="total_crashes")
    )
    crashes_by_intersection["years_observed"] = years_observed

    # Severity sub-counts. MAXSEVERITYCODE is a string in the raw GeoJSON — coerce.
    flags = pd.DataFrame({"intersection_id": matched["intersection_id"]})
    if "MAXSEVERITYCODE" in matched.columns:
        sev = pd.to_numeric(matched["MAXSEVERITYCODE"], errors="coerce").fillna(0)
        flags["injury_total"] = (sev >= 2).astype(int)  # injury or worse
        flags["ksi_total"]    = (sev >= 3).astype(int)  # killed or seriously injured (Vision Zero)
        flags["fatal_total"]  = (sev == 4).astype(int)
    else:
        flags["injury_total"] = 0
        flags["ksi_total"]    = 0
        flags["fatal_total"]  = 0

    # Ped / bike: OR-combine the structured count fields (pre-2018) with
    # keyword-parsed SDOT_COLDESC (still populated post-2018). Without the
    # fallback, the structured fields alone undercount ped/bike crashes by
    # ~100% for 2018+ records.
    desc = (matched.get("SDOT_COLDESC", pd.Series("", index=matched.index))
            .fillna("").str.upper())
    ped_count_flag  = (matched["PEDCOUNT"].fillna(0) > 0) \
        if "PEDCOUNT" in matched.columns else pd.Series(False, index=matched.index)
    bike_count_flag = (matched["PEDCYLCOUNT"].fillna(0) > 0) \
        if "PEDCYLCOUNT" in matched.columns else pd.Series(False, index=matched.index)
    ped_desc_flag  = desc.str.contains("PEDESTRIAN",   regex=False, na=False)
    bike_desc_flag = desc.str.contains("PEDALCYCLIST", regex=False, na=False)
    flags["ped_total"]  = (ped_count_flag  | ped_desc_flag).astype(int)
    flags["bike_total"] = (bike_count_flag | bike_desc_flag).astype(int)

    severity_cols = ["injury_total", "ksi_total", "fatal_total", "ped_total", "bike_total"]
    severity = flags.groupby("intersection_id")[severity_cols].sum().reset_index()
    crashes_by_intersection = crashes_by_intersection.merge(
        severity, on="intersection_id", how="left"
    )
    for col in severity_cols:
        crashes_by_intersection[col] = crashes_by_intersection[col].fillna(0).astype(int)

    return crashes_by_year, crashes_by_intersection


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # 1. Load
    intersections, collisions = load_inputs()
    print(f"Raw collisions loaded: {len(collisions)}")

    # Step 0 – schema inspection
    print("\n" + "=" * 60)
    junction_col, date_col = inspect_collisions_schema(collisions)
    print("=" * 60 + "\n")

    # Junction distribution on raw data (before any filter)
    print("--- Junction type distribution BEFORE filter ---")
    print(collisions[junction_col].value_counts(dropna=False).to_string())

    # 2. Filter: parse dates → junction allowlist → date range
    filtered, stats = filter_crashes(collisions, junction_col, date_col)

    print(f"\nDate parsing: {stats['nat_count']} rows with unparseable date (NaT)")
    print(f"Parsed year range: {stats['year_min_obs']} – {stats['year_max_obs']}  "
          f"(expect ~2003–2025)")
    print(f"Crashes after junction allowlist filter:    {stats['n_after_junction']}")
    print(f"Crashes after date filter ({YEAR_MIN}–{YEAR_MAX}):      {stats['n_after_date']}")

    print("\n--- Junction type distribution AFTER filter ---")
    print(filtered[junction_col].value_counts(dropna=False).to_string())

    # 3. Snap
    snapped  = snap_to_intersections(filtered, intersections)
    n_dropped = int(snapped["intersection_id"].isna().sum())
    n_snapped = int(snapped["intersection_id"].notna().sum())
    print(f"\nCrashes dropped (>{SNAP_DISTANCE_M} m from any intersection): {n_dropped}")
    print(f"Crashes snapped to an intersection:                          {n_snapped}")

    # 4. Build tables
    crashes_by_year, crashes_by_intersection = build_target_tables(snapped, intersections)

    # 5. Write outputs
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    crashes_by_year.to_parquet(OUT_DIR / "crashes_by_intersection_year.parquet", index=False)
    crashes_by_intersection.to_parquet(OUT_DIR / "crashes_by_intersection.parquet", index=False)
    print(f"\nWrote crashes_by_intersection_year.parquet  ({len(crashes_by_year)} rows)")
    print(f"Wrote crashes_by_intersection.parquet       ({len(crashes_by_intersection)} rows)")

    # 6. Sanity-check summary
    print("\n=== Sanity check: crashes_by_intersection ===")
    n_total = len(crashes_by_intersection)
    n_zero  = int((crashes_by_intersection["total_crashes"] == 0).sum())
    mean_c  = crashes_by_intersection["total_crashes"].mean()
    max_c   = crashes_by_intersection["total_crashes"].max()
    print(f"Total intersections:          {n_total}  (expect 651)")
    print(f"Intersections with 0 crashes: {n_zero}")
    print(f"Mean total_crashes:           {mean_c:.2f}")
    print(f"Max  total_crashes:           {max_c}")

    print("\ntotal_crashes value_counts:")
    print(crashes_by_intersection["total_crashes"].value_counts().sort_index().to_string())

    print("\nTop 10 intersections by total_crashes:")
    print(
        crashes_by_intersection.nlargest(10, "total_crashes")
        .to_string(index=False)
    )
