# project-cycle-group

Capitol Hill (Seattle) intersection crash-risk model and interactive map.

A Negative Binomial regression scores all **651 intersections** in Capitol Hill on their relative crash risk over the 2018–2023 window, with AASHTO Highway Safety Manual Empirical-Bayes adjustment. Results are exposed through a Streamlit + pydeck dashboard with a Claude-powered explainer that interprets each intersection's score in plain English.

## What the model does

- Fits `total_crashes ~ is_signalized + num_legs + max_speed_limit + bike_facility + C(arterial_class)` (statsmodels NB2, log link, `offset = log(years_observed)`).
- Excludes AADT (traffic volume) — the available coverage was too sparse over Capitol Hill. The infrastructure coefficients absorb some of the missing volume signal.
- Applies AASHTO HSM Part C Empirical-Bayes shrinkage (`w = 1 / (1 + α·predicted); eb = w·predicted + (1−w)·observed`) before ranking, so extreme model predictions are pulled toward observed counts.
- Reports `risk_score` as a **0–100 percentile rank**, not a calibrated crash count. Quintile cut-points define `risk_tier` (`very_high`, `high`, `moderate`, `low`, `very_low`).

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

- Map: all 651 intersections, colored by `risk_tier`, sized by `risk_score`.
- Sidebar: filter by tier, pick an intersection by ID.
- Side panel: score badge, expected-vs-actual crash counts, feature table.
- **Explain risk with Claude** button: streams a 2–3 paragraph explanation grounded in the model's actual feature values, the EB adjustment, and the intersection's percentile rank. Uses `claude-sonnet-4-6` with prompt caching on the system block.

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
  streamlit_app.py            Map + filters + side panel
  data_loader.py              Joins scores ⨝ predictions ⨝ features ⨝ intersections
  components/
    map.py                    pydeck ScatterplotLayer
    detail.py                 Side panel + Claude streaming
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

- **No AADT.** The infrastructure coefficients are inflated as a result. Adding a usable volume layer is the natural next iteration; the model fits cleanly with `log(aadt)` as an offset or predictor.
- **Capitol Hill scope only.** 651 intersections in a single neighborhood. Expanding to the rest of Seattle is a refit and re-snap, not an app change.
- **6-year observation window (2018–2023).** Re-fit when more recent collision data is available from SDOT.
- **Single-turn explainer.** Each click is a fresh request; no chat history. Sufficient for the demo, easy to extend.

## Archive

`detailed plan.pdf` was the original project plan. Retained for reference; the VLM and Supabase-export sections in it are no longer the implementation path. The README above is the source of truth.
