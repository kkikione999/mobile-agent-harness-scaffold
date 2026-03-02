from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _read_events(events_path: Path) -> list[dict[str, Any]]:
    if not events_path.exists():
        return []

    events: list[dict[str, Any]] = []
    for line in events_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        events.append(json.loads(line))
    return events


def _selector_drift_rate(events: list[dict[str, Any]]) -> float:
    selector_events = [
        e
        for e in events
        if isinstance(e.get("metadata"), dict) and isinstance(e["metadata"].get("selector"), dict)
    ]
    if not selector_events:
        return 0.0
    drifts = [
        e
        for e in selector_events
        if e.get("result", {}).get("error_code") == "selector_drift"
    ]
    return len(drifts) / len(selector_events)


def _evidence_complete(events: list[dict[str, Any]]) -> bool:
    for event in events:
        if event.get("phase") not in {"driver", "assertion"}:
            continue
        evidence = event.get("evidence")
        if not isinstance(evidence, dict):
            return False
        if not evidence.get("before_snapshot"):
            return False
        if not evidence.get("after_snapshot"):
            return False
        if not evidence.get("diff"):
            return False
    return True


def _required_changes_satisfied(events: list[dict[str, Any]], required_actions: list[str]) -> bool:
    if not required_actions:
        return True

    for action in required_actions:
        matched = [e for e in events if e.get("phase") == "driver" and e.get("action") == action]
        if not matched:
            return False
        has_change = any(
            int(e.get("evidence", {}).get("diff_summary", {}).get("change_count", 0)) > 0 for e in matched
        )
        if not has_change:
            return False
    return True


def _read_replay_score(run_dir: Path) -> float | None:
    replay_report = run_dir / "replay_report.json"
    if not replay_report.exists():
        return None
    payload = json.loads(replay_report.read_text(encoding="utf-8"))
    return float(payload.get("structural_consistency_score", 0.0))


def evaluate(run_dir: Path, rules_path: Path) -> dict[str, Any]:
    summary_path = run_dir / "summary.json"
    events_path = run_dir / "events.jsonl"
    meta_path = run_dir / "run_meta.json"

    summary = json.loads(summary_path.read_text(encoding="utf-8")) if summary_path.exists() else {}
    events = _read_events(events_path)
    rules = json.loads(rules_path.read_text(encoding="utf-8"))
    meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}

    error_events = [e for e in events if e.get("result", {}).get("status") == "error"]
    assertion_events = [e for e in events if e.get("phase") == "assertion"]
    duration = float(meta.get("duration_seconds", 0))
    selector_drift_rate = _selector_drift_rate(events)
    require_evidence_per_action = bool(rules.get("require_evidence_per_action", False))
    required_change_actions = [str(item) for item in rules.get("require_structural_change_for_actions", [])]
    replay_score = _read_replay_score(run_dir)
    replay_threshold = rules.get("replay_structural_consistency_threshold")
    max_selector_drift = float(rules.get("max_selector_drift_rate", 1.0))

    checks = {
        "error_events_within_limit": len(error_events) <= int(rules.get("max_error_events", 0)),
        "assertion_action_present": (not rules.get("require_assertion_action", False)) or bool(assertion_events),
        "duration_within_limit": duration <= float(rules.get("max_run_seconds", 120)),
        "evidence_complete_per_action": (not require_evidence_per_action) or _evidence_complete(events),
        "selector_drift_within_limit": selector_drift_rate <= max_selector_drift,
        "required_structural_changes_present": _required_changes_satisfied(events, required_change_actions),
    }
    if replay_threshold is not None:
        checks["replay_structural_consistency"] = replay_score is None or replay_score >= float(replay_threshold)

    passed = all(checks.values())
    report = {
        "passed": passed,
        "checks": checks,
        "counts": {
            "events": summary.get("events", len(events)),
            "error_events": len(error_events),
            "assertion_events": len(assertion_events),
            "selector_drifts": summary.get("selector_drifts", 0),
        },
        "duration_seconds": duration,
        "selector_drift_rate": selector_drift_rate,
        "replay_structural_consistency_score": replay_score,
    }

    (run_dir / "oracle_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report
