"""Check the output contract against private, independently adjudicated event labels."""
import csv
import json
import math
import os
import shutil
import signal
import subprocess
import tempfile
from pathlib import Path
from decimal import Decimal, ROUND_HALF_UP

SUBMISSION = Path("/root/solution.py")
SOURCE = Path("/root/data/river_event_observations.csv")
TEST_DATA = Path(__file__).resolve().parent / "data"
PRIVATE = TEST_DATA / "original_river_event_observations.csv"
HELDOUT = TEST_DATA / "reference_river_event_observations.csv"
LABEL_FILE = TEST_DATA / "adjudicated_labels.csv"
ARTIFACT = Path("/root/results/summary.json")
LABELS = {"runoff_pulse", "local_input", "sensor_artifact", "indeterminate"}
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
TOP_KEYS = {"event_count", "classification_counts", "events"}
EVENT_KEYS = {"event_id", "classification", "predicted_travel_time_hours",
              "observed_peak_lag_hours", "travel_time_difference_hours",
              "evidence_codes", "recommended_action"}
NUMERIC = ["timestamp_hour", "rainfall_mm", "reach_distance_km", "mean_velocity_m_s",
           "upstream_turbidity_ntu", "downstream_turbidity_ntu", "upstream_flow_m3_s",
           "downstream_flow_m3_s", "upstream_conductivity_us_cm", "downstream_conductivity_us_cm"]


def read_rows(path):
    with open(path, newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    for row in rows:
        for key in NUMERIC:
            try:
                value = float(row[key])
                row[key] = value if math.isfinite(value) else None
            except (TypeError, ValueError, KeyError):
                row[key] = None
        row["event_id"] = (row.get("event_id") or "").strip()
        row["downstream_sensor_status"] = (row.get("downstream_sensor_status") or "").strip()
    return rows


def expected_labels():
    with LABEL_FILE.open(newline="", encoding="utf-8") as f:
        pairs = [(r["event_id"], r["classification"]) for r in csv.DictReader(f)]
    result = dict(pairs)
    assert len(result) == len(pairs) and set(result.values()) <= LABELS
    return result


def span(values):
    vals = [v for v in values if v is not None]
    return max(vals) - min(vals) if len(vals) >= 2 else None


def peak(rows, key):
    candidates = [r for r in rows if r[key] is not None and r["timestamp_hour"] is not None]
    return min(candidates, key=lambda r: (-r[key], r["timestamp_hour"])) if candidates else None


def rounded(value):
    if value is None:
        return None
    return float(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def expected_metrics(rows):
    """Calculate physical metrics only; classification expectations come from separate adjudication data."""
    grouped = {}
    for row in rows:
        grouped.setdefault(row["event_id"], []).append(row)
    result = {}
    for eid, event in grouped.items():
        event = sorted(event, key=lambda r: r["timestamp_hour"])
        distances = [r["reach_distance_km"] for r in event if r["reach_distance_km"] is not None and r["reach_distance_km"] > 0]
        velocities = [r["mean_velocity_m_s"] for r in event if r["mean_velocity_m_s"] is not None and r["mean_velocity_m_s"] > 0]
        up, down = peak(event, "upstream_turbidity_ntu"), peak(event, "downstream_turbidity_ntu")
        predicted = distances[0] * 1000 / velocities[0] / 3600 if distances and velocities else None
        observed = down["timestamp_hour"] - up["timestamp_hour"] if up and down else None
        difference = abs(observed - predicted) if observed is not None and predicted is not None else None
        result[eid] = {
            "predicted_travel_time_hours": rounded(predicted),
            "observed_peak_lag_hours": rounded(observed),
            "travel_time_difference_hours": rounded(difference),
        }
    return result


def supported_codes(rows):
    """Return factual evidence codes supported by the observations; submitted evidence may be a subset."""
    event = sorted(rows, key=lambda r: r["timestamp_hour"])
    up, down = peak(event, "upstream_turbidity_ntu"), peak(event, "downstream_turbidity_ntu")
    rain = [r["rainfall_mm"] for r in event]
    known_rain = [v for v in rain if v is not None]
    codes = set()
    if any(v > 0 for v in known_rain): codes.add("rainfall_present")
    elif len(known_rain) == len(event) and all(v == 0 for v in known_rain): codes.add("no_rainfall_response")
    dist = next((r["reach_distance_km"] for r in event if r["reach_distance_km"] is not None and r["reach_distance_km"] > 0), None)
    vel = next((r["mean_velocity_m_s"] for r in event if r["mean_velocity_m_s"] is not None and r["mean_velocity_m_s"] > 0), None)
    lag = down["timestamp_hour"] - up["timestamp_hour"] if up and down else None
    predicted = dist * 1000 / vel / 3600 if dist is not None and vel is not None else None
    difference = abs(lag - predicted) if lag is not None and predicted is not None else None
    if lag is not None and lag > 0: codes.add("upstream_peak_precedes_downstream")
    if difference is not None:
        codes.add("travel_time_compatible" if difference <= 1 else "timing_not_compatible")
    upflow = [r["upstream_flow_m3_s"] for r in event if r["upstream_flow_m3_s"] is not None]
    if len(upflow) >= 2 and max(upflow) > min(upflow) * 1.2: codes.add("flow_increased")
    upt = [r["upstream_turbidity_ntu"] for r in event if r["upstream_turbidity_ntu"] is not None]
    if span(upt) is not None and span(upt) <= 2: codes.add("upstream_stable")
    dc = [r["downstream_conductivity_us_cm"] for r in event if r["downstream_conductivity_us_cm"] is not None]
    if span(dc) is not None and span(dc) >= 100: codes.add("downstream_conductivity_shift")
    dvals = [r["downstream_turbidity_ntu"] for r in event if r["downstream_turbidity_ntu"] is not None]
    if down and any(r is not down and r["downstream_turbidity_ntu"] is not None for r in event):
        other = [r["downstream_turbidity_ntu"] for r in event if r is not down and r["downstream_turbidity_ntu"] is not None]
        if other and down["downstream_turbidity_ntu"] >= 3 * max(other): codes.add("downstream_turbidity_spike")
    if down and down["downstream_sensor_status"].upper() == "FAULT": codes.add("sensor_fault_at_peak")
    df = [r["downstream_flow_m3_s"] for r in event if r["downstream_flow_m3_s"] is not None]
    if up and down and span(df) is not None and span(dc) is not None and span(df) < 2 and span(dc) < 20:
        codes.add("cross_channel_corroboration_absent")
    required = [k for k in NUMERIC if k != "timestamp_hour"]
    if any(r[k] is None for r in event for k in required) or any(r["downstream_sensor_status"].upper() in ("", "UNKNOWN", "NA", "N/A") for r in event):
        codes.add("key_measurements_missing")
    return codes


def run_program(input_path, output_path):
    """Run candidate as a mandatory unprivileged account with only its output directory writable."""
    if os.geteuid() != 0:
        raise AssertionError("Verifier must run as root so candidate privilege demotion cannot be skipped")
    base = output_path.parent.parent
    input_dir, output_dir = base / "input", base / "output"
    input_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)
    staged = input_dir / "observations.csv"
    shutil.copyfile(input_path, staged)
    os.chown(base, 0, 0); os.chmod(base, 0o755)
    os.chown(input_dir, 0, 0); os.chmod(input_dir, 0o755)
    os.chown(staged, 0, 0); os.chmod(staged, 0o444)
    script = base / "candidate.py"
    shutil.copyfile(SUBMISSION, script)
    os.chown(script, 0, 0); os.chmod(script, 0o444)
    os.chown(output_dir, 0, 0); os.chmod(output_dir, 0o777)
    command = ["/usr/bin/timeout", "--signal=TERM", "--kill-after=2s", "30s",
               "python", str(script), "--input", str(staged), "--output", str(output_path)]
    import pwd
    nobody = pwd.getpwnam("nobody")
    def demote():
        os.setgroups([]); os.setgid(nobody.pw_gid); os.setuid(nobody.pw_uid)
    proc = subprocess.Popen(command, cwd="/", stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, start_new_session=True, preexec_fn=demote,
                            env={"PATH": "/usr/local/bin:/usr/bin:/bin", "HOME": "/nonexistent", "LANG": "C.UTF-8"})
    try:
        stdout, stderr = proc.communicate(timeout=35)
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, signal.SIGTERM)
        try: proc.wait(timeout=2)
        except subprocess.TimeoutExpired: os.killpg(proc.pid, signal.SIGKILL); proc.wait(timeout=2)
        raise AssertionError("Submitted program exceeded the 30-second limit")
    assert proc.returncode == 0, f"Submitted program failed: {stderr}\n{stdout}"
    assert output_path.exists(), "Submitted program did not create the requested JSON output"
    return json.loads(output_path.read_text(encoding="utf-8"))


def validate_report(report, source_rows):
    """Validate representation before checking semantic answers to avoid type-confusion errors."""
    assert isinstance(report, dict) and set(report) == TOP_KEYS, "Unexpected top-level JSON keys"
    labels = expected_labels()
    metrics = expected_metrics(source_rows)
    groups = {}
    for row in source_rows: groups.setdefault(row["event_id"], []).append(row)
    expected_ids = sorted(groups)
    assert set(expected_ids) <= set(labels), "An event has no independent adjudication label"
    assert type(report["event_count"]) is int and report["event_count"] == len(expected_ids), "event_count mismatch"
    counts = report["classification_counts"]
    assert isinstance(counts, dict) and set(counts) == LABELS, "classification_counts has wrong labels"
    assert all(type(counts[k]) is int and counts[k] >= 0 for k in LABELS), "Counts must be nonnegative integers"
    events = report["events"]
    assert isinstance(events, list) and len(events) == len(expected_ids), "events length mismatch"
    for event in events:
        assert isinstance(event, dict), "Each event must be a JSON object"
        assert set(event) == EVENT_KEYS, "Unexpected event fields"
        assert isinstance(event["event_id"], str) and event["event_id"] in groups, "Unknown event_id"
        assert event["classification"] in LABELS, "Invalid classification"
        for key in ("predicted_travel_time_hours", "observed_peak_lag_hours", "travel_time_difference_hours"):
            value = event[key]
            assert value is None or (type(value) in (int, float) and math.isfinite(value)), f"{key} must be finite numeric or null"
        codes = event["evidence_codes"]
        assert isinstance(codes, list) and all(isinstance(c, str) for c in codes), "evidence_codes must be a string list"
        assert len(codes) == len(set(codes)) and codes == sorted(codes), "Evidence codes must be unique and alphabetically sorted"
        assert set(codes) <= CODES, "Unknown evidence code"
        assert set(codes) <= supported_codes(groups[event["event_id"]]), "An evidence code is not supported by the observations"
        eid = event["event_id"]
        assert event["classification"] == labels[eid], f"{eid}: classification disagrees with independent adjudication"
        assert event["recommended_action"] == ACTIONS[event["classification"]], f"{eid}: action does not match classification"
        for key, value in metrics[eid].items(): assert event[key] == value, f"{eid}: incorrect {key}"
    ids = [e["event_id"] for e in events]
    assert ids == expected_ids, "Events must be unique and sorted lexicographically"
    actual = {label: sum(e["classification"] == label for e in events) for label in LABELS}
    assert counts == actual, "classification_counts do not match event list"


def test_primary_uses_independent_adjudication_and_preserves_source():
    """Primary labels are checked against a separate verifier-only expert adjudication table."""
    original = PRIVATE.read_bytes()
    assert SOURCE.read_bytes() == original, "Agent-visible input differs from private original"
    rows = read_rows(PRIVATE)
    with tempfile.TemporaryDirectory(prefix="river_v11_primary_") as td:
        base = Path(td); os.chmod(base, 0o755)
        report = run_program(PRIVATE, base / "output" / "summary.json")
        validate_report(report, rows)
    assert PRIVATE.read_bytes() == original and SOURCE.read_bytes() == original, "Input source was modified"


def test_heldout_records_use_event_keyed_adjudications():
    """Held-out IDs differ from primary IDs and expected labels are keyed, never positional."""
    rows = read_rows(HELDOUT)
    with tempfile.TemporaryDirectory(prefix="river_v11_heldout_") as td:
        base = Path(td); os.chmod(base, 0o755)
        report = run_program(HELDOUT, base / "output" / "summary.json")
        validate_report(report, rows)


def test_declared_primary_artifact_matches_contract():
    """The task's required primary artifact must exist and satisfy the same output contract."""
    assert ARTIFACT.exists(), "Required artifact /root/results/summary.json is missing"
    validate_report(json.loads(ARTIFACT.read_text(encoding="utf-8")), read_rows(PRIVATE))


def test_reversed_rows_do_not_change_event_results():
    """Chronological measurement conventions make metrics independent of CSV row ordering."""
    rows = list(reversed(read_rows(PRIVATE)))
    with tempfile.TemporaryDirectory(prefix="river_v11_reversed_") as td:
        base = Path(td); os.chmod(base, 0o755)
        path = base / "reversed.csv"
        with path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(rows[0].keys())); writer.writeheader(); writer.writerows(rows)
        report = run_program(path, base / "output" / "summary.json")
        validate_report(report, rows)


def test_missing_rainfall_is_unknown_not_absent():
    """Missing rainfall cannot justify a negative rainfall evidence code or local-input label."""
    rows = [r.copy() for r in read_rows(PRIVATE) if r["event_id"] == "EV-08"]
    for row in rows: row["rainfall_mm"] = None
    with tempfile.TemporaryDirectory(prefix="river_v11_missing_rain_") as td:
        base = Path(td); os.chmod(base, 0o755)
        path = base / "missing.csv"
        with path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(rows[0].keys())); writer.writeheader(); writer.writerows(rows)
        # This perturbed event is not in the adjudication table; validate its conservative behavior directly.
        report = run_program(path, base / "output" / "summary.json")
        event = report["events"][0]
        assert event["classification"] == "indeterminate"
        assert "no_rainfall_response" not in event["evidence_codes"]


def test_empty_input_returns_typed_empty_report():
    """A header-only CSV yields the well-defined zero-event report."""
    with tempfile.TemporaryDirectory(prefix="river_v11_empty_") as td:
        base = Path(td); os.chmod(base, 0o755)
        path = base / "empty.csv"
        with path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f); writer.writerow(NUMERIC[:1] + ["event_id"] + NUMERIC[1:] + ["downstream_sensor_status"])
        report = run_program(path, base / "output" / "summary.json")
        assert report == {"event_count": 0, "classification_counts": {k: 0 for k in LABELS}, "events": []}
