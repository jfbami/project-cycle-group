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


if __name__ == "__main__":
    main()
