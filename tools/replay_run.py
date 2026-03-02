#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _read_events(run_dir: Path) -> list[dict[str, Any]]:
    path = run_dir / "events.jsonl"
    if not path.exists():
        return []
    events: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        events.append(json.loads(line))
    return events


def _run_replay(scenario_path: Path, platform: str, run_root: Path, dispatch_commands: bool) -> Path:
    env = dict(os.environ)
    env["DISPATCH_COMMANDS"] = "1" if dispatch_commands else "0"
    cmd = [
        sys.executable,
        str(REPO_ROOT / "tools" / "run_scenario.py"),
        "--scenario",
        str(scenario_path),
        "--platform",
        platform,
        "--run-root",
        str(run_root),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False, cwd=REPO_ROOT, env=env)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or proc.stdout.strip() or "replay run failed")

    run_line = next((line for line in proc.stdout.splitlines() if line.startswith("run complete: ")), "")
    if not run_line:
        raise RuntimeError("replay run did not return run directory")
    return Path(run_line.replace("run complete: ", "", 1).strip())


def _compare_runs(original_run: Path, replay_run: Path) -> dict[str, Any]:
    original_events = _read_events(original_run)
    replay_events = _read_events(replay_run)

    original_driver = [e for e in original_events if e.get("phase") == "driver"]
    replay_driver = [e for e in replay_events if e.get("phase") == "driver"]
    original_assert = [e for e in original_events if e.get("phase") == "assertion"]
    replay_assert = [e for e in replay_events if e.get("phase") == "assertion"]

    total_checks = 0
    matched_checks = 0
    mismatches: list[dict[str, Any]] = []

    for idx, left in enumerate(original_driver):
        if idx >= len(replay_driver):
            mismatches.append({"type": "missing_driver_event", "index": idx, "action": left.get("action")})
            total_checks += 1
            continue
        right = replay_driver[idx]
        total_checks += 1
        if left.get("action") == right.get("action") and left.get("evidence", {}).get("after_tree_hash") == right.get(
            "evidence", {}
        ).get("after_tree_hash"):
            matched_checks += 1
        else:
            mismatches.append(
                {
                    "type": "driver_mismatch",
                    "index": idx,
                    "original_action": left.get("action"),
                    "replay_action": right.get("action"),
                    "original_after_tree_hash": left.get("evidence", {}).get("after_tree_hash"),
                    "replay_after_tree_hash": right.get("evidence", {}).get("after_tree_hash"),
                }
            )

    for idx, left in enumerate(original_assert):
        if idx >= len(replay_assert):
            mismatches.append({"type": "missing_assertion_event", "index": idx, "action": left.get("action")})
            total_checks += 1
            continue
        right = replay_assert[idx]
        total_checks += 1
        if left.get("result", {}).get("verdict") == right.get("result", {}).get("verdict"):
            matched_checks += 1
        else:
            mismatches.append(
                {
                    "type": "assertion_mismatch",
                    "index": idx,
                    "original_verdict": left.get("result", {}).get("verdict"),
                    "replay_verdict": right.get("result", {}).get("verdict"),
                }
            )

    score = 1.0 if total_checks == 0 else matched_checks / total_checks
    return {
        "mode": "structural",
        "original_run_dir": str(original_run),
        "replay_run_dir": str(replay_run),
        "total_checks": total_checks,
        "matched_checks": matched_checks,
        "structural_consistency_score": score,
        "passed": score >= 0.9,
        "mismatches": mismatches,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Replay a prior run and compare structural consistency.")
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--mode", default="structural", choices=["structural"])
    parser.add_argument("--run-root", default="runs")
    args = parser.parse_args()

    original_run = Path(args.run_dir)
    meta_path = original_run / "run_meta.json"
    if not meta_path.exists():
        raise SystemExit(f"missing run metadata: {meta_path}")

    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    scenario_path = Path(meta["scenario_path"])
    platform = str(meta["platform"])
    dispatch_commands = bool(meta.get("dispatch_commands", False))

    replay_run = _run_replay(scenario_path, platform, Path(args.run_root), dispatch_commands)
    report = _compare_runs(original_run, replay_run)
    output_path = original_run / "replay_report.json"
    output_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print(f"replay report: {output_path}")
    print(f"structural consistency score: {report['structural_consistency_score']:.3f}")


if __name__ == "__main__":
    main()
