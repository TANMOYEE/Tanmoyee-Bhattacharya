#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cp "$SCRIPT_DIR/solve_task.py" /root/solution.py
python /root/solution.py --input /root/data/river_event_observations.csv --output /root/results/summary.json
