# River Event Diagnosis Using Travel Time and Sensor Evidence

This task asks for event-specific river diagnosis from reach travel time, upstream/downstream turbidity, flow, conductivity, rainfall, and sensor status. The verifier uses a separate event-keyed adjudication table for classification labels, independently calculates physical metrics, and checks that submitted evidence codes are both allowed and supported.

## Package contents
- `instruction.md`: scientific objective, screening conventions, and exact output contract
- `task.toml`: task metadata and declared artifacts
- `environment/`: primary synthetic observations and runtime image
- `solution/`: reference implementation and launcher
- `tests/`: verifier-only original and held-out records, independent adjudication labels, contract tests, and unprivileged execution. The verifier image stages the original primary CSV at `/root/data/river_event_observations.csv`. Test fixtures are resolved relative to `tests/test_task.py`, so the package does not depend on hard-coded `/tests/data` paths.

Author email: `tanmoyee.b@turing.com`.

These synthetic observations are screening examples only; they do not establish a pollution source or causation. Local tests should be run inside the Terminal Bench test container. Passing local checks does not guarantee official Turing acceptance.
