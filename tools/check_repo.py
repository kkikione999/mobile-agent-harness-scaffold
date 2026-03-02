#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from harness.driver.dsl import load_scenario
from harness.oracle.evaluator import evaluate

REQUIRED_PATHS = [
    "README.md",
    "AGENTS.md",
    "docs/architecture.md",
    "rules/oracle_rules.json",
    "tools/run_scenario.py",
]


def validate_scenarios() -> list[str]:
    errors: list[str] = []
    for path in (REPO_ROOT / "scenarios").rglob("*.json"):
        try:
            obj = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            errors.append(f"invalid json in {path}: {exc}")
            continue

        for key in ("name", "platform", "app", "steps"):
            if key not in obj:
                errors.append(f"{path} missing key: {key}")

        if not isinstance(obj.get("steps", None), list) or not obj.get("steps"):
            errors.append(f"{path} has empty or invalid steps")
            continue

        try:
            load_scenario(path)
        except ValueError as exc:
            errors.append(f"scenario dsl error in {path}: {exc}")
    return errors


def validate_smoke_executable() -> list[str]:
    errors: list[str] = []
    scenario = REPO_ROOT / "scenarios" / "smoke" / "cold_start_android.json"
    if not scenario.exists():
        errors.append(f"missing smoke scenario: {scenario}")
        return errors

    env = dict(os.environ)
    env["DISPATCH_COMMANDS"] = "0"

    with tempfile.TemporaryDirectory(prefix="harness-check-") as tmp:
        run_cmd = [
            sys.executable,
            str(REPO_ROOT / "tools" / "run_scenario.py"),
            "--scenario",
            str(scenario),
            "--platform",
            "android",
            "--run-root",
            tmp,
        ]
        run_proc = subprocess.run(run_cmd, capture_output=True, text=True, check=False, cwd=REPO_ROOT, env=env)
        if run_proc.returncode != 0:
            errors.append(f"smoke run failed: {run_proc.stderr.strip() or run_proc.stdout.strip()}")
            return errors

        run_line = next(
            (line for line in run_proc.stdout.splitlines() if line.startswith("run complete: ")),
            "",
        )
        if not run_line:
            errors.append("smoke run did not print run directory")
            return errors

        run_dir = Path(run_line.replace("run complete: ", "", 1).strip())
        try:
            report = evaluate(run_dir, REPO_ROOT / "rules" / "oracle_rules.json")
        except Exception as exc:  # pragma: no cover - defensive check path
            errors.append(f"smoke eval crashed: {exc}")
            return errors

        if not report.get("passed", False):
            errors.append(f"smoke eval failed: {json.dumps(report, ensure_ascii=True)}")

    return errors


def main() -> None:
    missing = [p for p in REQUIRED_PATHS if not (REPO_ROOT / p).exists()]
    scenario_errors = validate_scenarios()
    smoke_errors = validate_smoke_executable()

    if missing or scenario_errors or smoke_errors:
        for path in missing:
            print(f"missing required path: {path}")
        for error in scenario_errors:
            print(error)
        for error in smoke_errors:
            print(error)
        raise SystemExit(1)

    print("repo check passed")


if __name__ == "__main__":
    main()
