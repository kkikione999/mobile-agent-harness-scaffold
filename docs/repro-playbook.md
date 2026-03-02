# Repro Playbook

When a run fails:

1. Evaluate: `make eval RUN_DIR=runs/<run-id>`
2. Replay for structural consistency: `make replay RUN_DIR=runs/<run-id>`
3. Package: `make package-failure RUN_DIR=runs/<run-id>`
4. Share bundle and include:
   - simulator name
   - app build version
   - scenario file used
   - exact command line used

A valid repro package should contain at least `events.jsonl`, `summary.json`, `run_meta.json`, and `oracle_report.json`.
For bridge-enabled runs, include `raw_trees/` and `capture_traces/` as part of the failure package.
