#!/usr/bin/env python3
import argparse
import csv
import json
import math
from collections import Counter
from pathlib import Path

LABELS = ("runoff_pulse", "local_input", "sensor_artifact", "indeterminate")
ACTIONS = {
    "runoff_pulse": "Schedule event-based downstream sampling during the next rainfall response.",
    "local_input": "Collect paired upstream and downstream samples and inspect nearby potential inputs.",
    "sensor_artifact": "Inspect and verify the downstream turbidity sensor before treating the spike as a river event.",
    "indeterminate": "Repeat paired sampling with complete sensor-quality and conductivity records during the next event.",
}
CODES = {
    "rainfall_present", "flow_increased", "upstream_peak_precedes_downstream",
    "travel_time_compatible", "downstream_conductivity_shift", "upstream_stable",
    "downstream_turbidity_spike", "sensor_fault_at_peak",
    "cross_channel_corroboration_absent", "key_measurements_missing",
    "timing_not_compatible", "no_rainfall_response",
}


def finite(value):
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def rounded(value, places=2):
    if value is None:
        return None
    # Python's round is deterministic; use decimal half-up through a string to make the contract explicit.
    from decimal import Decimal, ROUND_HALF_UP
    return float(Decimal(str(value)).quantize(Decimal("1").scaleb(-places), rounding=ROUND_HALF_UP))


def peak_row(rows, key):
    usable = [r for r in rows if r[key] is not None and r["timestamp_hour"] is not None]
    if not usable:
        return None
    # Earlier timestamp wins a tie.
    return min(usable, key=lambda r: (-r[key], r["timestamp_hour"]))


def span(values):
    v = [x for x in values if x is not None]
    return max(v)-min(v) if len(v) >= 2 else None


def classify(rows):
    rows = sorted(rows, key=lambda r: r["timestamp_hour"])
    codes = []
    up_peak = peak_row(rows, "upstream_turbidity_ntu")
    down_peak = peak_row(rows, "downstream_turbidity_ntu")
    rain = [r["rainfall_mm"] for r in rows if r["rainfall_mm"] is not None]
    flows = [r["upstream_flow_m3_s"] for r in rows if r["upstream_flow_m3_s"] is not None]
    down_cond = [r["downstream_conductivity_us_cm"] for r in rows if r["downstream_conductivity_us_cm"] is not None]
    up_turb = [r["upstream_turbidity_ntu"] for r in rows if r["upstream_turbidity_ntu"] is not None]
    down_turb = [r["downstream_turbidity_ntu"] for r in rows if r["downstream_turbidity_ntu"] is not None]

    rainfall_present = any(v > 0 for v in rain)
    rainfall_complete = len(rain) == len(rows) and all(v is not None for v in rain)
    rainfall_absent = rainfall_complete and all(v == 0 for v in rain)
    if rainfall_present:
        codes.append("rainfall_present")
    elif rainfall_absent:
        codes.append("no_rainfall_response")

    dist = next((r["reach_distance_km"] for r in rows if r["reach_distance_km"] is not None and r["reach_distance_km"] > 0), None)
    velocity = next((r["mean_velocity_m_s"] for r in rows if r["mean_velocity_m_s"] is not None and r["mean_velocity_m_s"] > 0), None)
    predicted = (dist * 1000 / velocity / 3600) if dist is not None and velocity is not None else None
    observed = (down_peak["timestamp_hour"] - up_peak["timestamp_hour"]) if up_peak and down_peak else None
    difference = abs(observed-predicted) if observed is not None and predicted is not None else None

    if up_peak and down_peak and observed > 0:
        codes.append("upstream_peak_precedes_downstream")
    if difference is not None and difference <= 1.0:
        codes.append("travel_time_compatible")
    elif difference is not None:
        codes.append("timing_not_compatible")

    if len(flows) >= 2 and max(flows) > min(flows) * 1.2:
        codes.append("flow_increased")
    if span(up_turb) is not None and span(up_turb) <= 2.0:
        codes.append("upstream_stable")
    if len(down_cond) >= 2 and span(down_cond) is not None and span(down_cond) >= 100:
        codes.append("downstream_conductivity_shift")

    fault_peak = bool(down_peak and down_peak["downstream_sensor_status"].upper() == "FAULT")
    neighbors = [r["downstream_turbidity_ntu"] for r in rows
                 if r is not down_peak and r["downstream_turbidity_ntu"] is not None]
    isolated_spike = bool(down_peak and neighbors and down_peak["downstream_turbidity_ntu"] >= 3 * max(neighbors))
    if isolated_spike:
        codes.append("downstream_turbidity_spike")
    if fault_peak:
        codes.append("sensor_fault_at_peak")

    cond_shift = "downstream_conductivity_shift" in codes
    stable_up = "upstream_stable" in codes
    down_flow_span = span([r["downstream_flow_m3_s"] for r in rows if r["downstream_flow_m3_s"] is not None])
    down_cond_span = span(down_cond)
    corroboration_absent = (
        down_peak is not None and up_peak is not None
        and down_flow_span is not None and down_cond_span is not None
        and down_flow_span < 2 and down_cond_span < 20
    )
    if corroboration_absent:
        codes.append("cross_channel_corroboration_absent")

    missing = any(r[k] is None for r in rows for k in (
        "rainfall_mm","reach_distance_km","mean_velocity_m_s",
        "upstream_turbidity_ntu","downstream_turbidity_ntu",
        "upstream_flow_m3_s","downstream_flow_m3_s",
        "upstream_conductivity_us_cm","downstream_conductivity_us_cm"
    )) or any(r["downstream_sensor_status"].upper() in ("", "UNKNOWN", "NA", "N/A") for r in rows)
    if missing:
        codes.append("key_measurements_missing")

    # Scientific decision integrates the travel-time test and corroborating channels.
    if fault_peak and isolated_spike and corroboration_absent:
        label = "sensor_artifact"
    elif (rainfall_absent and stable_up and down_peak and up_peak
          and down_peak["downstream_turbidity_ntu"] >= 2 * up_peak["upstream_turbidity_ntu"]
          and cond_shift):
        label = "local_input"
    elif (rainfall_present and "upstream_peak_precedes_downstream" in codes
          and "travel_time_compatible" in codes
          and ("flow_increased" in codes or cond_shift)
          and up_turb and down_turb
          and up_peak["upstream_turbidity_ntu"] >= 2 * min(up_turb)
          and down_peak["downstream_turbidity_ntu"] >= 2 * min(down_turb)):
        label = "runoff_pulse"
    else:
        label = "indeterminate"
    return label, predicted, observed, difference, sorted(set(codes))


def analyze(input_path, output_path):
    required = set([
        "event_id","timestamp_hour","rainfall_mm","reach_distance_km","mean_velocity_m_s",
        "upstream_turbidity_ntu","downstream_turbidity_ntu","upstream_flow_m3_s",
        "downstream_flow_m3_s","upstream_conductivity_us_cm","downstream_conductivity_us_cm",
        "downstream_sensor_status"
    ])
    with open(input_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames or not required.issubset(reader.fieldnames):
            raise ValueError("Input CSV is missing required columns")
        raw = list(reader)
    groups = {}
    for row in raw:
        event_id = (row.get("event_id") or "").strip()
        if not event_id:
            raise ValueError("event_id must not be empty")
        item = {"event_id": event_id, "downstream_sensor_status": (row.get("downstream_sensor_status") or "").strip()}
        for key in required - {"event_id","downstream_sensor_status"}:
            item[key] = finite(row.get(key))
        if item["timestamp_hour"] is None:
            raise ValueError("timestamp_hour must be numeric")
        groups.setdefault(event_id, []).append(item)

    events = []
    for event_id in sorted(groups):
        label, predicted, observed, difference, codes = classify(groups[event_id])
        events.append({
            "event_id": event_id,
            "classification": label,
            "predicted_travel_time_hours": rounded(predicted),
            "observed_peak_lag_hours": rounded(observed),
            "travel_time_difference_hours": rounded(difference),
            "evidence_codes": codes,
            "recommended_action": ACTIONS[label],
        })
    counts = Counter(e["classification"] for e in events)
    output = {
        "event_count": len(events),
        "classification_counts": {label: counts.get(label, 0) for label in LABELS},
        "events": events,
    }
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, allow_nan=False)
        f.write("\n")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    analyze(args.input, args.output)


if __name__ == "__main__":
    main()
