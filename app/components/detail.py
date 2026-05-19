"""Side panel showing one intersection's score, features, and explainer button."""
from __future__ import annotations

import os

import streamlit as st

_ARTERIAL_LABEL = {
    0: "Local / non-arterial",
    1: "Principal arterial",
    2: "Minor arterial",
    3: "Collector arterial",
    4: "NOS arterial",
    5: "Other arterial subclass",
}

_TIER_BADGE = {
    "very_high": ("Very high risk", "#d72638"),
    "high":      ("High risk",       "#e85f00"),
    "moderate":  ("Moderate",        "#f0b400"),
    "low":       ("Low",             "#78af50"),
    "very_low":  ("Very low",        "#2882c8"),
}


def _fmt(value, fmt: str = "") -> str:
    if value is None or value != value:
        return "—"
    if fmt:
        try:
            return format(value, fmt)
        except (TypeError, ValueError):
            return str(value)
    return str(value)


def render(row: dict | None):
    """Render the detail panel for the selected row (or placeholder when None)."""
    if row is None:
        st.info("Click an intersection on the map, or pick one from the sidebar.")
        return

    tier = row.get("risk_tier", "unknown")
    label, color = _TIER_BADGE.get(tier, (tier, "#888"))
    st.markdown(
        f"<div style='display:inline-block; padding:4px 10px; border-radius:4px; "
        f"background:{color}; color:white; font-weight:600; font-size:13px;'>"
        f"{label}</div>",
        unsafe_allow_html=True,
    )

    st.markdown(f"### `{row.get('intersection_id', '?')}`")

    col1, col2, col3 = st.columns(3)
    col1.metric("Score", _fmt(row.get("risk_score"), ".1f"))
    col2.metric("Rank", f"{int(row.get('risk_rank', 0))} / 651")
    col3.metric("Crashes 2018–23", int(row.get("actual_total") or 0))

    st.markdown("**Model expected vs. actual**")
    a, b, c = st.columns(3)
    a.metric("Expected (6-yr)", _fmt(row.get("expected_total"), ".2f"))
    b.metric("Actual",          int(row.get("actual_total") or 0))
    c.metric("EB / year",       _fmt(row.get("eb_estimate_per_year"), ".3f"))

    st.markdown("**Features**")
    arterial_class = int(row.get("arterial_class") or 0)
    arterial_label = _ARTERIAL_LABEL.get(arterial_class, f"class {arterial_class}")
    st.table({
        "Feature": [
            "Signalized",
            "Number of legs",
            "Max speed limit",
            "Bike facility (≤15 m)",
            "Arterial class",
        ],
        "Value": [
            "Yes" if row.get("is_signalized") else "No",
            str(int(row.get("num_legs") or 0)),
            f"{_fmt(row.get('max_speed_limit'))} mph",
            "Yes" if row.get("bike_facility") else "No",
            f"{arterial_label} ({arterial_class})",
        ],
    })

    st.divider()
    if st.button("Explain risk with Claude", use_container_width=True, type="primary"):
        _stream_explanation(row)


def _stream_explanation(row: dict):
    """Stream the Claude explainer into the side panel."""
    api_key = st.secrets.get("ANTHROPIC_API_KEY") if hasattr(st, "secrets") else None
    api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        st.error(
            "ANTHROPIC_API_KEY not set. Add it to `.streamlit/secrets.toml` "
            "(`ANTHROPIC_API_KEY = \"sk-ant-...\"`) and rerun."
        )
        return

    from app.llm.explainer import explain_intersection

    try:
        st.write_stream(explain_intersection(row, api_key=api_key))
    except Exception as e:
        st.error(f"Explainer failed: {e}")
