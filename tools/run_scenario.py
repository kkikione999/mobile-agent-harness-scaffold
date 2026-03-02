#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from harness.driver.android import AndroidDriver
from harness.driver.dsl import Scenario, load_scenario
from harness.driver.ios import IOSDriver
from harness.driver.selectors import make_selector
from harness.evidence.bus import EvidenceBus

ASSERTION_ACTIONS = {"assert_visible", "assert_eventually", "expect_transition"}


def _normalize_selector(step: dict[str, Any], platform: str) -> dict[str, Any] | None:
    selector = step.get("selector")
    if isinstance(selector, dict):
        payload = dict(selector)
        payload.setdefault("platform_hint", platform)
        return payload
    if "target" in step:
        return make_selector(by="id", value=str(step["target"]), platform_hint=platform)
    return None


def _driver_for(platform: str, scenario: Scenario, dispatch_commands: bool) -> AndroidDriver | IOSDriver:
    if platform == "android":
        return AndroidDriver(app=scenario.app, dispatch_commands=dispatch_commands)
    if platform == "ios":
        return IOSDriver(app=scenario.app, dispatch_commands=dispatch_commands)
    raise ValueError(f"unsupported platform: {platform}")


def _execute_with_retry(driver: AndroidDriver | IOSDriver, step: dict[str, Any]) -> tuple[dict[str, Any], int]:
    retries = int(step.get("retries", 0))
    max_attempts = max(1, retries + 1)
    last_result: dict[str, Any] = {"status": "error", "details": "action did not run"}

    for attempt in range(1, max_attempts + 1):
        result = driver.interact(step)
        last_result = result
        if result.get("status") not in {"error", "fail"}:
            return result, attempt
    return last_result, max_attempts


def _extract_snapshot_artifacts(
    snapshot: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any] | list[Any] | None, dict[str, Any] | None]:
    payload = dict(snapshot)
    raw_tree = payload.pop("raw_tree", None)
    capture_trace = payload.pop("capture_trace", None)
    if not isinstance(capture_trace, dict):
        capture_trace = None
    return payload, raw_tree, capture_trace


def _run(platform: str, scenario: Scenario, run_dir: Path, dispatch_commands: bool) -> dict[str, Any]:
    bus = EvidenceBus(run_dir=run_dir)
    driver = _driver_for(platform, scenario, dispatch_commands)

    preflight = driver.preflight()
    if preflight.get("status") in {"error", "fail"}:
        before_full = driver.snapshot({"compact": True, "interactive_only": True})
        before, before_raw, before_trace = _extract_snapshot_artifacts(before_full)
        after = dict(before)
        diff = driver.diff(before, after)

        before_ref = bus.write_snapshot(0, "before", before)
        after_ref = bus.write_snapshot(0, "after", after)
        diff_ref = bus.write_diff(0, diff)
        raw_before_ref = None
        raw_after_ref = None
        trace_before_ref = None
        trace_after_ref = None
        if isinstance(before_raw, (dict, list)):
            raw_before_ref = bus.write_raw_tree(0, "before", before_raw)
            raw_after_ref = bus.write_raw_tree(0, "after", before_raw)
        if before_trace:
            trace_before_ref = bus.write_capture_trace(0, "before", before_trace)
            trace_after_ref = bus.write_capture_trace(0, "after", before_trace)

        evidence = {
            "schema_version": "evidence.v2",
            "before_snapshot": before_ref,
            "after_snapshot": after_ref,
            "normalized_before": before_ref,
            "normalized_after": after_ref,
            "raw_tree_before": raw_before_ref,
            "raw_tree_after": raw_after_ref,
            "capture_trace_before": trace_before_ref,
            "capture_trace_after": trace_after_ref,
            "diff": diff_ref,
            "before_tree_hash": before.get("tree_hash"),
            "after_tree_hash": after.get("tree_hash"),
            "diff_summary": {
                "change_count": diff.get("change_count", 0),
                "change_types": diff.get("change_types", []),
            },
        }
        metadata = {
            "schema_version": before.get("schema_version"),
            "app_integration_status": "error",
            "bridge_protocol_version": preflight.get("health_payload", {}).get("protocol_version")
            if isinstance(preflight.get("health_payload"), dict)
            else None,
        }
        bus.record_event(
            phase="driver",
            action="bridge_preflight",
            command=None,
            result=preflight,
            step_index=0,
            evidence=evidence,
            metadata=metadata,
        )
        bus.finalize(
            extra={
                "platform": platform,
                "schema_version": "run.v3",
                "dsl_version": scenario.dsl_version,
                "preflight_failed": True,
            }
        )
        return {
            "steps": [
                {
                    "index": 0,
                    "action": "bridge_preflight",
                    "result": preflight,
                    "assertion": None,
                    "evidence": evidence,
                }
            ]
        }

    step_results: list[dict[str, Any]] = []
    for idx, original_step in enumerate(scenario.steps):
        step = dict(original_step)
        selector = _normalize_selector(step, platform)
        if selector:
            step["selector"] = selector
            step.setdefault("selector_anchor", selector.get("anchor"))

        before_full = driver.snapshot({"compact": True, "interactive_only": True})
        before, before_raw, before_trace = _extract_snapshot_artifacts(before_full)
        interact_result, attempt = _execute_with_retry(driver, step)
        after_full = driver.snapshot({"compact": True, "interactive_only": True})
        after, after_raw, after_trace = _extract_snapshot_artifacts(after_full)
        diff = driver.diff(before, after)

        assertion_result: dict[str, Any] | None = None
        if step["action"] in ASSERTION_ACTIONS:
            assertion_result = driver.verify(step)

        before_ref = bus.write_snapshot(idx, "before", before)
        after_ref = bus.write_snapshot(idx, "after", after)
        diff_ref = bus.write_diff(idx, diff)
        raw_before_ref = None
        raw_after_ref = None
        trace_before_ref = None
        trace_after_ref = None
        if isinstance(before_raw, (dict, list)):
            raw_before_ref = bus.write_raw_tree(idx, "before", before_raw)
        if isinstance(after_raw, (dict, list)):
            raw_after_ref = bus.write_raw_tree(idx, "after", after_raw)
        if before_trace:
            trace_before_ref = bus.write_capture_trace(idx, "before", before_trace)
        if after_trace:
            trace_after_ref = bus.write_capture_trace(idx, "after", after_trace)

        evidence = {
            "schema_version": "evidence.v2",
            "before_snapshot": before_ref,
            "after_snapshot": after_ref,
            "normalized_before": before_ref,
            "normalized_after": after_ref,
            "raw_tree_before": raw_before_ref,
            "raw_tree_after": raw_after_ref,
            "capture_trace_before": trace_before_ref,
            "capture_trace_after": trace_after_ref,
            "diff": diff_ref,
            "before_tree_hash": before.get("tree_hash"),
            "after_tree_hash": after.get("tree_hash"),
            "capture_source_before": before.get("capture_source"),
            "capture_source_after": after.get("capture_source"),
            "diff_summary": {
                "change_count": diff.get("change_count", 0),
                "change_types": diff.get("change_types", []),
            },
        }
        metadata = {
            "max_attempts": max(1, int(step.get("retries", 0)) + 1),
            "attempt_used": attempt,
            "schema_version": after.get("schema_version"),
            "bridge_protocol_version": after.get("normalization_report", {}).get("version")
            if isinstance(after.get("normalization_report"), dict)
            else None,
            "app_integration_status": "error" if interact_result.get("bridge_error_code") else "ok",
        }
        if selector:
            metadata["selector"] = selector

        bus.record_event(
            phase="driver",
            action=step["action"],
            command=interact_result.get("command"),
            result=interact_result,
            step_index=idx,
            evidence=evidence,
            metadata=metadata,
        )

        if assertion_result is not None:
            bus.record_event(
                phase="assertion",
                action=step["action"],
                command=None,
                result=assertion_result,
                step_index=idx,
                evidence=evidence,
                metadata={"selector": selector, **metadata} if selector else metadata,
            )

        step_results.append(
            {
                "index": idx,
                "action": step["action"],
                "result": interact_result,
                "assertion": assertion_result,
                "evidence": evidence,
            }
        )

    bus.finalize(extra={"platform": platform, "schema_version": "run.v3", "dsl_version": scenario.dsl_version})
    return {"steps": step_results}


def main() -> None:
    parser = argparse.ArgumentParser(description="Run one scenario on a target platform.")
    parser.add_argument("--scenario", required=True, help="Path to scenario json")
    parser.add_argument("--platform", required=True, choices=["android", "ios"])
    parser.add_argument("--run-root", default="runs", help="Output root directory")
    args = parser.parse_args()

    started = datetime.now(timezone.utc)
    scenario = load_scenario(args.scenario)

    if scenario.platform != args.platform:
        raise ValueError(f"scenario platform mismatch: scenario={scenario.platform}, cli={args.platform}")

    run_id = started.strftime("%Y%m%dT%H%M%SZ") + f"-{scenario.name}"
    run_dir = Path(args.run_root) / run_id

    dispatch_commands = os.getenv("DISPATCH_COMMANDS", "0") == "1"
    result = _run(args.platform, scenario, run_dir, dispatch_commands)

    ended = datetime.now(timezone.utc)
    duration_seconds = (ended - started).total_seconds()
    meta = {
        "schema_version": "run.v3",
        "run_id": run_id,
        "started_at": started.isoformat(),
        "ended_at": ended.isoformat(),
        "duration_seconds": duration_seconds,
        "scenario_path": str(Path(args.scenario).resolve()),
        "platform": args.platform,
        "dispatch_commands": dispatch_commands,
        "dsl_version": scenario.dsl_version,
        "steps": result["steps"],
    }
    (run_dir / "run_meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")

    print(f"run complete: {run_dir}")


if __name__ == "__main__":
    main()
