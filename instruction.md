# Diagnose River Turbidity Events Using Travel Time and Sensor Evidence

A monitoring team has four river-event records. For each event, decide whether the observations are most consistent with a rainfall-associated runoff pulse, a localized downstream water-quality change, a turbidity sensor artifact, or an indeterminate event. The aim is to prioritize follow-up monitoring, not to prove a pollution source.

The input is `/root/data/river_event_observations.csv`. Create `/root/solution.py`, a reusable Python program accepting `--input PATH` and `--output PATH`. Run it on the primary CSV and save the report to `/root/results/summary.json`. The program will also be run on a separate held-out CSV with the same columns. Each invocation has a 30-second limit.

Use `timestamp_hour` to compare the timing of the upstream and downstream turbidity peaks. Estimate the expected travel time through the monitored reach as distance in metres divided by velocity in metres per second, then convert seconds to hours. Use the first positive finite distance and velocity in the event; if either is unavailable, report `null`. For a turbidity peak tied across rows, use the earliest timestamp. Calculate the observed peak lag as the downstream peak time minus the upstream peak time. Round travel-time metrics to two decimal places using decimal round-half-up. Consider whether the observed peak delay is compatible with that estimate, and evaluate rainfall, flow, conductivity, and sensor status together. A sensor-status fault aligned with an isolated turbidity spike should be treated differently from a corroborated change in the river. Missing measurements are unknown, not zero. Do not infer illegality or hazard from these data alone.

Use these classification labels:
- `runoff_pulse`: a rainfall-associated turbidity response has upstream-to-downstream timing compatible with the reach travel-time estimate and is corroborated by flow or another water-quality channel.
- `local_input`: a downstream turbidity/conductivity change is not accompanied by a comparable upstream change or rainfall response.
- `sensor_artifact`: an isolated downstream turbidity spike aligns with a fault status and lacks corroboration from flow or conductivity.
- `indeterminate`: the available observations do not adequately distinguish the explanations.

For every event, provide evidence codes selected only from this vocabulary:
- `rainfall_present`
- `flow_increased`
- `upstream_peak_precedes_downstream`
- `travel_time_compatible`
- `downstream_conductivity_shift`
- `upstream_stable`
- `downstream_turbidity_spike`
- `sensor_fault_at_peak`
- `cross_channel_corroboration_absent`
- `key_measurements_missing`
- `timing_not_compatible`
- `no_rainfall_response`

Include only codes supported by the event's measurements. Return the codes in ascending lexicographic (alphabetical) order, with no duplicates. The report should contain computed travel-time and observed-lag values when they can be determined; otherwise use `null`. The evidence codes are a compact, auditable summary of the observations, not a substitute for the classification. A `no_rainfall_response` code is supported only when rainfall is recorded for every row in the event and every recorded value is zero. If any rainfall measurement is missing and no positive rainfall value is present, rainfall status is unknown; do not infer absence of rainfall. For the first positive finite reach distance and velocity, inspect rows in ascending `timestamp_hour` order.

Write `/root/results/summary.json` as a JSON object with exactly these top-level keys:
- `event_count`: integer number of distinct event IDs
- `classification_counts`: object with exactly the four classification labels above as keys and integer counts
- `events`: list of one object per event, sorted by `event_id` in ascending lexicographic order. Each object must contain exactly:
  - `event_id`: string from the input
  - `classification`: one of the four labels
  - `predicted_travel_time_hours`: estimated reach travel time in hours, rounded to two decimals, or `null` if distance or velocity is missing or invalid
  - `observed_peak_lag_hours`: downstream turbidity peak timestamp minus upstream peak timestamp, in hours, or `null` if either peak cannot be determined
  - `travel_time_difference_hours`: absolute difference between observed lag and predicted travel time, rounded to two decimals, or `null` if either value is unavailable
  - `evidence_codes`: list of supported codes from the vocabulary above, with no duplicates
  - `recommended_action`: one complete sentence ending in a period and appropriate to the classification

The classification counts must match the event list. Do not add extra keys. Recommended actions should be cautious and actionable: verify a suspected sensor issue, collect paired samples for a possible localized change, schedule event-based sampling for a likely runoff pulse, or gather better data for an indeterminate event. Do not allege a specific polluter or claim causation as established.

Interpret each event as a whole time series rather than applying a universal turbidity cutoff. Establish the event's background from its own observations, then assess whether the upstream and downstream peaks form a plausible sequence for the reach, whether rainfall and flow provide a hydrological explanation, whether conductivity independently corroborates a water-quality change, and whether the sensor status undermines confidence in an isolated spike. The observations are hourly, so account for that sampling resolution when judging whether observed and estimated travel times are consistent. A local-input interpretation requires a clear downstream-specific change without a supported rainfall response; do not use it when rainfall is unknown. A sensor-artifact interpretation requires an isolated downstream spike aligned with a fault status and lacking corroboration in other channels. If important evidence is missing or the explanations cannot be distinguished, choose `indeterminate`. These are event-level screening judgments for the supplied synthetic observations, not universal regulatory thresholds or proof of causation.

Use these exact action sentences:
- `runoff_pulse`: `Schedule event-based downstream sampling during the next rainfall response.`
- `local_input`: `Collect paired upstream and downstream samples and inspect nearby potential inputs.`
- `sensor_artifact`: `Inspect and verify the downstream turbidity sensor before treating the spike as a river event.`
- `indeterminate`: `Repeat paired sampling with complete sensor-quality and conductivity records during the next event.`


Execution constraints: the program must work from a working directory other than `/root`, must not depend on privileged access or files next to the program, and must not write to the input. During held-out execution the program is copied to a temporary directory and run as an unprivileged user; the input file is read-only and only the designated output directory is writable.

Scoring is binary: required files, output structure and types, event-derived travel-time calculations, classifications, supported evidence codes, recommended actions, and source-file integrity must all be correct.

You have 600 seconds to complete this task. Do not cheat by using online solutions or hints specific to this task.
