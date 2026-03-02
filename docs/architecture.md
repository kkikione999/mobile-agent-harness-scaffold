# Harness Architecture

## Layers

1. Device Harness: boots and resets Android Emulator / iOS Simulator.
2. Device Bridge: unified `snapshot / diff / interact / verify / replay` interface.
3. Platform Adapters: Android and iOS adapters that compile shared actions into native commands.
4. Evidence Bus: writes events, snapshots, and diffs into `runs/<run-id>/`.
5. Oracle Engine: applies machine-checkable pass/fail rules on evidence.
6. Triage Bundle: packages failure artifacts for replay and root-cause analysis.

## Data flow

1. `tools/run_scenario.py` loads scenario JSON.
2. Bridge captures `before` compact accessibility snapshot.
3. Adapter executes interaction command and optional retry.
4. Bridge captures `after` snapshot and computes structural diff.
5. Verification loop evaluates assertions with polling and evidence.
6. Evidence bus writes:
   - `events.jsonl`
   - `snapshots/<step>-before.json`
   - `snapshots/<step>-after.json`
   - `raw_trees/<step>-before.json`
   - `raw_trees/<step>-after.json`
   - `capture_traces/<step>-before.json`
   - `capture_traces/<step>-after.json`
   - `diffs/<step>.json`
7. `tools/evaluate_run.py` scores the run with oracle rules.
8. `tools/replay_run.py` replays and computes structural consistency score.
9. `tools/package_failure.py` creates a tarball for failed runs.

## Determinism notes

- Run metadata always includes scenario path, platform, and timestamps.
- Output path uses one run id to correlate all evidence.
- Unknown or unsupported actions are explicit errors, not silent skips.
- Element refs use deterministic anchors (`id/label/type/text/path`) with confidence-based fallback.
- Replay validates structural consistency first (not pixel equality).
- Android dispatch mode expects target-app bridge integration and emits hard-fail diagnostics when bridge health is not ready.
