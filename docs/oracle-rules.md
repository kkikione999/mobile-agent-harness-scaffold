# Oracle Rules

Oracle rules are in `rules/oracle_rules.json` and currently include:

- `max_error_events`: hard fail when exceeded.
- `require_assertion_action`: require at least one assertion-style action.
- `max_run_seconds`: hard fail when run duration exceeds threshold.
- `require_evidence_per_action`: require `before/after/diff` evidence for driver and assertion events.
- `max_selector_drift_rate`: fail when selector drift exceeds threshold.
- `require_structural_change_for_actions`: action list that must produce non-empty structural diffs.
- `require_bridge_health_event`: require a successful `bridge_preflight` event.
- `replay_structural_consistency_threshold`: replay score threshold when replay report exists.

You can extend these rules as long as `harness/oracle/evaluator.py` and tests are updated together.
