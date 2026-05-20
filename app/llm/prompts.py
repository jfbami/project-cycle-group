"""
Prompts for the intersection risk explainer.

The system prompt is intentionally thorough — it bakes in the AASHTO HSM
context and feature semantics so the model can produce grounded explanations
without RAG. Kept under ~1.5K tokens so it's easy to iterate on; will not
hit Sonnet 4.6's 2048-token cache minimum and that's fine for a demo.
"""

SYSTEM_PROMPT = """You produce a concise analytical fact sheet for one Capitol Hill intersection. Output is a structured readout, not a narrative.

THE MODEL (background — do not lecture the reader about it)
Negative Binomial regression on 651 Capitol Hill intersections, target = total crashes 2018-2023, formula:
   total_crashes ~ is_signalized + num_legs + max_speed_limit + bike_facility + C(arterial_class)
with offset = log(years_observed). AADT excluded; arterial_class and max_speed_limit coefficients absorb the missing volume signal and are inflated.

Fitted coefficient signs (use these to attribute Key drivers — do not invent magnitudes):
   is_signalized   positive  (signalized locations correlate with more crashes — volume proxy)
   num_legs        positive  (more legs -> more conflict points)
   bike_facility   negative  (presence associated with fewer predicted crashes)
   arterial_class  strongly positive at every class >= 1 vs class 0
   max_speed_limit negative residual (counterintuitive — AADT-confounding; do not name as a "key driver" unless asked)

EMPIRICAL-BAYES (AASHTO HSM Part C):  w = 1/(1+alpha*predicted);  EB = w*predicted + (1-w)*observed.
Pulls extreme predictions toward observed counts. Direction:
   observed > predicted -> EB shifts UP
   observed < predicted -> EB shifts DOWN
   observed = predicted -> ~unchanged

risk_score = percentile rank of EB-adjusted per-year estimate. Tiers: very_high >= 90, high 70-89, moderate 40-69, low 20-39, very_low < 20.

OUTPUT — strict markdown. No prose paragraphs.

**Tier:** <tier> · percentile <X.X> · rank <N>/651
**Exposure:** <terse comma list — signalized?, # legs, speed mph, bike facility?, arterial class label>

**Key drivers**
- <feature value> — <one clause tying it to the model coefficient sign>
- <feature value> — <one clause>
(2 to 4 bullets, ordered by largest plausible model contribution first. Skip features whose value puts them at baseline — e.g. skip "arterial_class 0" or "no signal" unless they're the protective story for a low-tier intersection.)

**Model vs observed (6-yr window)**
- Predicted: <expected_total> crashes (<expected_per_year>/yr raw)
- Observed: <actual_total> crashes
- EB-adjusted: <eb_per_year>/yr · shifted <UP|DOWN|~unchanged> because observed <exceeded|matched|fell short of> the model

**Severity:** <injury> injury · <ksi> KSI · <fatal> fatal · <ped> ped · <bike> bike

CONSTRAINTS
- Use only values from the user message. Never invent.
- No prose paragraphs. No "this intersection has" sentences. No softening language.
- No adjectives: "concerning", "significant", "elevated", "alarming", "noteworthy".
- Do not recommend interventions.
- Do not explain general traffic engineering concepts. State the data; let it stand.
- Same format for every tier. Do not soften for low-risk intersections; do not amplify for high-risk.
- Total output <= 140 words. Stop after the Severity line."""


_ARTERIAL_LABEL = {
    0: "local / non-arterial",
    1: "principal arterial",
    2: "minor arterial",
    3: "collector arterial",
    4: "not-otherwise-classified arterial",
    5: "other arterial subclass",
}


def _fmt(value, fmt: str = "") -> str:
    """Format a numeric value, returning 'unknown' for None/NaN."""
    if value is None:
        return "unknown"
    try:
        if value != value:  # NaN check
            return "unknown"
    except TypeError:
        pass
    if fmt:
        try:
            return format(value, fmt)
        except (TypeError, ValueError):
            return str(value)
    return str(value)


def build_user_message(row: dict) -> str:
    """Build the per-intersection user prompt from a joined-data row dict."""
    arterial_class = int(row.get("arterial_class", 0) or 0)
    arterial_label = _ARTERIAL_LABEL.get(arterial_class, f"class {arterial_class}")

    return f"""Explain the risk profile of intersection {row.get('intersection_id', '?')}.

RISK METRICS
  risk_score (0-100 percentile):       {_fmt(row.get('risk_score'), '.1f')}
  risk_tier:                            {row.get('risk_tier', 'unknown')}
  risk_rank (1 = highest risk):         {_fmt(row.get('risk_rank'))} of 651

CRASH HISTORY (2018-2023, 6-year window)
  model expected (raw, 6-yr total):     {_fmt(row.get('expected_total'), '.2f')}
  actual recorded crashes:              {_fmt(row.get('actual_total'))}
  EB-adjusted estimate (per year):      {_fmt(row.get('eb_estimate_per_year'), '.3f')}
  raw model estimate (per year):        {_fmt(row.get('expected_crashes_per_year'), '.3f')}

SEVERITY BREAKDOWN (counts of crashes meeting each criterion)
  injuries:                             {_fmt(row.get('injury_total'))}
  KSI (Killed/Seriously Injured):       {_fmt(row.get('ksi_total'))}
  fatal:                                {_fmt(row.get('fatal_total'))}
  ped-involved:                         {_fmt(row.get('ped_total'))}
  bike-involved:                        {_fmt(row.get('bike_total'))}

FEATURES
  signalized:                           {'yes' if row.get('is_signalized') else 'no'}
  number of legs:                       {_fmt(row.get('num_legs'))}
  max posted speed limit (mph):         {_fmt(row.get('max_speed_limit'))}
  bike facility within 15 m:            {'yes' if row.get('bike_facility') else 'no'}
  arterial classification:              {arterial_label} (class {arterial_class})
"""
