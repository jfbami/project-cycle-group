"""Capitol Hill intersection-risk map + Claude explainer.

Run with:
    streamlit run app/streamlit_app.py
"""
from __future__ import annotations

import streamlit as st

from app.components import detail, map as map_view
from app.data_loader import load_joined

TIER_ORDER = ["very_high", "high", "moderate", "low", "very_low"]


@st.cache_data
def _load() -> "pd.DataFrame":
    return load_joined()


def main():
    st.set_page_config(
        page_title="Capitol Hill — Intersection Risk",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    st.title("Capitol Hill Intersection Risk")
    st.caption(
        "651 intersections · Negative Binomial regression + AASHTO HSM "
        "Empirical-Bayes adjustment · risk_score is a 0–100 percentile rank."
    )

    try:
        df = _load()
    except FileNotFoundError as e:
        st.error(str(e))
        st.stop()

    st.sidebar.subheader("Filter")
    # (sidebar definition continues below; scorecard is rendered between
    # caption and the map column, after filtering is applied)
    tiers = st.sidebar.multiselect(
        "Risk tier",
        options=TIER_ORDER,
        default=TIER_ORDER,
        help="Show only intersections in the selected tier(s).",
    )
    filtered = df[df["risk_tier"].isin(tiers)] if tiers else df.iloc[0:0]
    st.sidebar.caption(f"Showing {len(filtered)} of {len(df)} intersections")

    st.sidebar.divider()
    st.sidebar.subheader("Inspect intersection")
    id_options = ["—"] + sorted(filtered["intersection_id"].tolist())
    picked_from_sidebar = st.sidebar.selectbox(
        "By ID",
        options=id_options,
        index=0,
        help="Pick an intersection ID from the filtered set.",
    )

    # --- Vision Zero scorecard (aggregate over the currently filtered set) ---
    _render_scorecard(filtered)

    map_col, detail_col = st.columns([7, 3], gap="medium")

    with map_col:
        event = map_view.render(filtered, key="main_map")

    clicked_id = map_view.picked_id(event)

    selected_id = (
        clicked_id
        if clicked_id
        else (picked_from_sidebar if picked_from_sidebar != "—" else None)
    )

    row = None
    if selected_id:
        match = df[df["intersection_id"] == selected_id]
        if not match.empty:
            row = match.iloc[0].to_dict()

    with detail_col:
        detail.render(row)


def _render_scorecard(filtered_df):
    """Vision Zero aggregate scorecard over the currently filtered set.

    Capitol Hill 2018-2023 has very few KSI / ped / bike crashes in SDOT's
    data — partly because the per-crash ped/bike fields were poorly
    populated post-2018. The zeros are informative, not a bug.
    """
    if filtered_df.empty:
        return

    total_crashes = int(filtered_df["actual_total"].sum())
    injury        = int(filtered_df["injury_total"].sum())
    ksi           = int(filtered_df["ksi_total"].sum())
    fatal         = int(filtered_df["fatal_total"].sum())
    pedbike       = int(filtered_df["ped_total"].sum() + filtered_df["bike_total"].sum())

    st.markdown("##### Vision Zero scorecard — Capitol Hill 2018–2023")
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Total crashes",     f"{total_crashes:,}")
    c2.metric("Injury collisions", f"{injury:,}")
    c3.metric("KSI",               f"{ksi:,}", help="Killed or Seriously Injured — Vision Zero's target metric (goal = 0 by 2030)")
    c4.metric("Fatalities",        f"{fatal:,}")
    c5.metric("Ped/bike-involved", f"{pedbike:,}", help="See data-quality finding below — this count is suspect.")

    # Ped/bike counts above use both PEDCOUNT/PEDCYLCOUNT (pre-2018) and a
    # SDOT_COLDESC keyword fallback (post-2018); see pipeline/snap_crashes.py.

    # Top by severity (defaults to injury since KSI is mostly zero in this window)
    rank_col = "ksi_total" if ksi > 0 else "injury_total"
    if filtered_df[rank_col].sum() > 0:
        with st.expander(f"Top intersections by {rank_col.replace('_', ' ')}", expanded=False):
            top = (
                filtered_df.nlargest(5, [rank_col, "actual_total"])
                [["intersection_id", "risk_tier", "actual_total",
                  "injury_total", "ksi_total", "fatal_total"]]
            )
            st.dataframe(top, hide_index=True, use_container_width=True)


if __name__ == "__main__":
    main()
