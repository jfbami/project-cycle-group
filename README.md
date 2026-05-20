# project-cycle-group

Capitol Hill (Seattle) intersection crash-risk model and interactive map.

A Negative Binomial regression scores all **651 intersections** in Capitol Hill on their relative crash risk over the 2018–2023 window, with AASHTO Highway Safety Manual Empirical-Bayes adjustment. Results are exposed through a Streamlit + pydeck dashboard with a Claude-powered explainer that interprets each intersection's score in plain English.

## What the model does

- Fits `total_crashes ~ is_signalized + num_legs + max_speed_limit + bike_facility + C(arterial_class)` (statsmodels NB2, log link, `offset = log(years_observed)`).
- Excludes AADT (traffic volume) — the available coverage was too sparse over Capitol Hill. The infrastructure coefficients absorb some of the missing volume signal.
- Applies AASHTO HSM Part C Empirical-Bayes shrinkage (`w = 1 / (1 + α·predicted); eb = w·predicted + (1−w)·observed`) before ranking, so extreme model predictions are pulled toward observed counts.
- Reports `risk_score` as a **0–100 percentile rank**, not a calibrated crash count. `risk_tier` cut-points: `very_high` ≥ 90, `high` 70–89, `moderate` 40–69, `low` 20–39, `very_low` < 20 (very_high is the top ~10% so it reads as severe).

## Vision Zero framing

The pipeline also emits five severity counts per intersection from SDOT's `MAXSEVERITYCODE`:
- `injury_total` — any injury collision (code ≥ 2)
- `ksi_total` — Killed or Seriously Injured (code ≥ 3, the Vision Zero target metric)
- `fatal_total` — fatal only (code = 4)
- `ped_total` / `bike_total` — count of crashes with `PEDCOUNT > 0` / `PEDCYLCOUNT > 0`

The Streamlit app surfaces these in a scorecard at the top of the page (filter-aware) and per intersection in the detail panel. Capitol Hill 2018–23 has 4 injury crashes and 0 KSI at the 651 intersections — that's the actual data, and "0 KSI" is itself a meaningful Vision Zero baseline (whether it represents true success or partial under-reporting). **Caveat:** SDOT's per-crash `PEDCOUNT` / `PEDCYLCOUNT` fields appear sparsely populated for records post-2018; the displayed ped/bike count is conservative.

## Counterfactual / "what-if" intervention modeling

The detail panel's **What if...** expander lets you set hypothetical feature values (toggle signal, add bike facility, downgrade arterial, change speed limit, change # of legs) and see the model's predicted Δ in expected crashes/year. Useful for evaluating intervention scenarios.

**Important caveat:** the model excludes AADT, so the `arterial_class` and `max_speed_limit` coefficients absorb the missing traffic-volume signal. Counterfactual Δ should be treated as **directional, not calibrated**. In particular, lowering `max_speed_limit` can show a *positive* Δ (worse) — that's because the model is reading low posted speeds as a proxy for low-traffic residential streets without enough other signal to separate the two.

## Why we dropped the VLM

An earlier plan (`detailed plan.pdf`) had a Vision-Language Model scoring near-miss events from Seattle traffic-camera footage, blended into the score via an optional `vlm_events_by_intersection.parquet`. We removed it: the data was never collected, manual footage collection is high-effort and tangential to the safety question, and the EB-only ranking is now production. If anyone on the team is still mid-stream on VLM work, please re-sync — `pipeline/score_risk.py` no longer accepts the parquet and `has_vlm_data` is gone from the output schema. The plan PDF is retained for archival only.

## Pipeline

Run in order. The first script downloads ~5 MB from Seattle's GeoData ArcGIS portal (a few minutes on first run; cached as GeoJSON afterward). On Windows, prefix each command with `python -X utf8` to avoid `cp1252` encoding errors on Unicode print statements.

```sh
python seattle_arcgis.py              # download raw layers -> data/raw/
python pipeline/build_intersections.py   # 651 intersection points -> data/intermediate/intersections.parquet
python pipeline/snap_crashes.py          # crashes per intersection per year
python pipeline/assemble_features.py     # feature matrix (signal, legs, speed, bike, arterial)
python pipeline/fit_risk_model.py        # NB regression -> data/model/nb_v1_no_aadt.pkl
python pipeline/score_risk.py            # EB + percentile ranks -> data/intermediate/intersection_scores.parquet
```

## App

```sh
pip install -r requirements.txt

# Set your Anthropic API key for the explainer (gitignored)
cp .streamlit/secrets.toml.example .streamlit/secrets.toml
# then edit secrets.toml and paste your key

streamlit run app/streamlit_app.py
```

- **Vision Zero scorecard** at the top: total crashes, injuries, KSI, fatalities, ped/bike-involved — recomputed over the current tier filter.
- **Map**: all 651 intersections, colored by `risk_tier`, sized by `risk_score`. Hover for tooltip, click to populate the side panel.
- **Sidebar**: filter by tier, pick an intersection by ID.
- **Side panel**: score badge, expected-vs-actual crash counts, severity breakdown, feature table.
- **Explain risk with Claude** button: streams a 2–3 paragraph explanation grounded in the model's actual feature values, the EB adjustment, the intersection's percentile rank, and severity counts. Uses `claude-haiku-4-5` (≈ 0.25¢ per click).
- **What if... expander**: counterfactual intervention modeling — set hypothetical features and see the predicted Δ in expected crashes/year.

## File layout

```
seattle_arcgis.py             ArcGIS REST fetcher (one function per Seattle dataset)
pipeline/
  build_intersections.py      Street endpoints -> clustered intersection points
  snap_crashes.py             Crashes within 25 m -> per-intersection counts
  assemble_features.py        Per-intersection features (signal, legs, speed, ...)
  fit_risk_model.py           NB2 SPF fit + predictions
  score_risk.py               EB shrinkage + percentile rank + tier
app/
  streamlit_app.py            Map + filters + side panel + Vision Zero scorecard
  data_loader.py              Joins scores ⨝ predictions ⨝ features ⨝ intersections
  counterfactual.py           Load pkl + predict at hypothetical feature configurations
  components/
    map.py                    pydeck ScatterplotLayer
    detail.py                 Side panel + Claude streaming + "What if..." expander
  llm/
    prompts.py                System prompt + per-intersection user prompt builder
    explainer.py              Anthropic client + CLI entry point
.streamlit/
  config.toml                 Theme + dev settings
  secrets.toml.example        Template — copy to secrets.toml (gitignored)
```

## CLI tools

Run the explainer standalone for prompt iteration without booting Streamlit:

```sh
set ANTHROPIC_API_KEY=sk-ant-...
python -m app.llm.explainer <intersection_id>
```

Get sample IDs per tier:

```sh
python -X utf8 -m app.data_loader
```

## Known limitations

- **No AADT.** The infrastructure coefficients are inflated as a result. Adding a usable volume layer is the natural next iteration; the model fits cleanly with `log(aadt)` as an offset or predictor. The counterfactual UI surfaces this caveat next to its prediction.
- **Capitol Hill scope only.** 651 intersections in a single neighborhood. Expanding to the rest of Seattle is a refit and re-snap, not an app change.
- **6-year observation window (2018–2023).** Re-fit when more recent collision data is available from SDOT.
- **SDOT ped/bike severity fields are sparse post-2018.** `PEDCOUNT` / `PEDCYLCOUNT` are essentially zero for records in the 2018+ window in this dump. The Vision Zero scorecard shows that honestly; treat the ped/bike count as a lower bound.
- **Counterfactual is directional, not calibrated.** Without AADT, `arterial_class` and `max_speed_limit` absorb the missing volume signal, so Δ values are illustrative — particularly weird at the boundaries (lowering speed can show *positive* Δ, an artifact of the confounding, not a real effect).
- **Single-turn explainer.** Each click is a fresh request; no chat history. Sufficient for the demo, easy to extend.

## Archive

`detailed plan.pdf` was the original project plan. Retained for reference; the VLM and Supabase-export sections in it are no longer the implementation path. The README above is the source of truth.
