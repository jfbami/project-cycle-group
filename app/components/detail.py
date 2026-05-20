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

    # Vision Zero severity breakdown
    injury = int(row.get("injury_total") or 0)
    ksi    = int(row.get("ksi_total") or 0)
    fatal  = int(row.get("fatal_total") or 0)
    ped    = int(row.get("ped_total") or 0)
    bike   = int(row.get("bike_total") or 0)
    st.markdown(
        f"**Severity (2018–23):** {injury} injury · {ksi} KSI · "
        f"{fatal} fatal · {ped} ped · {bike} bike"
    )

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

    _render_counterfactual(row)


_ARTERIAL_CHOICE_FMT = {
    0: "0 — local / non-arterial",
    1: "1 — principal arterial",
    2: "2 — minor arterial",
    3: "3 — collector arterial",
    4: "4 — NOS arterial",
    5: "5 — other arterial subclass",
}


def _render_counterfactual(row: dict):
    """'What if...' expander — predict expected crashes/year under hypothetical features."""
    iid = row.get("intersection_id", "?")
    with st.expander("What if... (intervention modeling)", expanded=False):
        st.caption(
            "Counterfactual prediction from the fitted Negative Binomial model. "
            "The model excludes traffic volume (AADT); arterial-class and speed "
            "effects absorb some volume signal and are inflated — treat Δ as "
            "directional, not calibrated."
        )

        new_sig = st.checkbox(
            "Signalized",
            value=bool(row.get("is_signalized")),
            key=f"cf_sig_{iid}",
        )
        new_legs = st.number_input(
            "Number of legs",
            min_value=3, max_value=8,
            value=int(row.get("num_legs") or 4),
            key=f"cf_legs_{iid}",
        )
        new_speed = st.slider(
            "Max speed limit (mph)",
            min_value=15, max_value=55,
            value=int(row.get("max_speed_limit") or 25),
            step=5,
            key=f"cf_spd_{iid}",
        )
        new_bike = st.checkbox(
            "Bike facility within 15 m",
            value=bool(row.get("bike_facility")),
            key=f"cf_bike_{iid}",
        )
        cur_art = int(row.get("arterial_class") or 0)
        new_art = st.selectbox(
            "Arterial class",
            options=[0, 1, 2, 3, 4, 5],
            index=cur_art,
            format_func=lambda x: _ARTERIAL_CHOICE_FMT.get(x, str(x)),
            key=f"cf_art_{iid}",
        )

        overrides = {
            "is_signalized":   int(new_sig),
            "num_legs":        int(new_legs),
            "max_speed_limit": float(new_speed),
            "bike_facility":   int(new_bike),
            "arterial_class":  int(new_art),
        }

        try:
            from app.counterfactual import compare
            result = compare(row, overrides)
        except Exception as e:
            st.error(f"Counterfactual failed: {e}")
            return

        delta_label = "—"
        if result["pct_change"] == result["pct_change"]:  # not NaN
            delta_label = f"{result['delta']:+.3f}/yr ({result['pct_change']:+.0f}%)"
        st.metric(
            "Expected crashes / year (hypothetical)",
            value=f"{result['hypothetical_per_year']:.3f}",
            delta=delta_label,
            delta_color="inverse",  # negative delta = good = green
            help=f"Current: {result['current_per_year']:.3f} crashes/year. "
                 "Lower is better, so green = predicted reduction.",
        )


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
