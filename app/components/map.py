"""pydeck ScatterplotLayer of all Capitol Hill intersections, colored by risk_tier."""
from __future__ import annotations

import pandas as pd
import pydeck as pdk
import streamlit as st

TIER_COLORS = {
    "very_high": [215, 38, 56],
    "high":      [232, 95, 0],
    "moderate":  [240, 180, 0],
    "low":       [120, 175, 80],
    "very_low":  [40, 130, 200],
}

INITIAL_VIEW = pdk.ViewState(
    latitude=47.622,
    longitude=-122.317,
    zoom=13.8,
    pitch=0,
    bearing=0,
)


def _enrich(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["color"] = df["risk_tier"].map(TIER_COLORS)
    df["radius"] = 8 + (df["risk_score"].fillna(0) / 100) * 22
    return df


def render(df: pd.DataFrame, key: str = "main_map"):
    """Render the map and return Streamlit's selection event (may be None / empty)."""
    data = _enrich(df)

    layer = pdk.Layer(
        "ScatterplotLayer",
        id="intersections",
        data=data,
        get_position=["lon", "lat"],
        get_fill_color="color",
        get_radius="radius",
        pickable=True,
        auto_highlight=True,
        stroked=True,
        get_line_color=[20, 20, 20, 80],
        line_width_min_pixels=1,
        radius_min_pixels=4,
        radius_max_pixels=22,
    )

    tooltip = {
        "html": (
            "<b>{intersection_id}</b><br/>"
            "score {risk_score} &middot; tier {risk_tier}<br/>"
            "{actual_total} crashes 2018-2023"
        ),
        "style": {
            "backgroundColor": "rgba(30,30,30,0.92)",
            "color": "white",
            "fontFamily": "sans-serif",
            "fontSize": "12px",
            "padding": "6px 8px",
        },
    }

    deck = pdk.Deck(
        layers=[layer],
        initial_view_state=INITIAL_VIEW,
        tooltip=tooltip,
        map_style="light",
    )

    try:
        return st.pydeck_chart(
            deck,
            on_select="rerun",
            selection_mode="single-object",
            use_container_width=True,
            height=620,
            key=key,
        )
    except TypeError:
        # Older Streamlit without on_select support — render without click handling.
        st.pydeck_chart(deck, use_container_width=True, height=620, key=key)
        return None


def picked_id(event) -> str | None:
    """Pull the picked intersection_id out of a pydeck_chart selection event."""
    if event is None:
        return None
    try:
        objects = event.selection.objects.get("intersections", [])
    except AttributeError:
        return None
    if not objects:
        return None
    return objects[0].get("intersection_id")
