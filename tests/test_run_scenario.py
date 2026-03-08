from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from harness.driver.dsl import Scenario
from harness.oracle.evaluator import evaluate
from tools import run_scenario


class _FakeDriver:
    def __init__(self) -> None:
        self.snapshot_calls = 0
        self.verify_calls = 0

    def preflight(self) -> dict[str, str]:
        return {"status": "ok"}

    def snapshot(self, options: dict[str, object] | None = None) -> dict[str, object]:
        _ = options
        self.snapshot_calls += 1
        tree_hash = f"tree-{self.snapshot_calls}"
        return {
            "schema_version": "cat.v2",
            "platform": "android",
            "captured_at": f"2026-03-09T00:00:0{self.snapshot_calls}Z",
            "root": "@e0",
            "elements": [
                {
                    "ref": "@e0",
                    "id": "home_screen",
                    "label": "Home",
                    "type": "view",
                    "text": "Home",
                    "path": "0",
                    "ordinal": 0,
                }
            ],
            "tree_hash": tree_hash,
            "capture_source": "fake_capture",
            "normalization_report": {"version": "fake.v1"},
            "raw_tree": {"tree_hash": tree_hash},
            "capture_trace": {"tree_hash": tree_hash},
        }

    def interact(
        self,
        action: dict[str, object],
        *,
        elements: list[dict[str, object]] | None = None,
        snapshot: dict[str, object] | None = None,
    ) -> dict[str, object]:
        _ = (elements, snapshot)
        if action["action"] == "assert_visible":
            return {"status": "ok", "details": "assertion action uses verification loop", "command": None}
        return {"status": "recorded", "command": "adb shell input tap 10 10"}

    def verify(self, assertion: dict[str, object]) -> dict[str, object]:
        _ = assertion
        self.verify_calls += 1
        return {"status": "ok", "verdict": "pass", "snapshot_tree_hash": f"verify-{self.verify_calls}"}

    def diff(self, before: dict[str, object], after: dict[str, object]) -> dict[str, object]:
        changed = before.get("tree_hash") != after.get("tree_hash")
        return {
            "schema_version": "cat.diff.v2",
            "before_tree_hash": before.get("tree_hash"),
            "after_tree_hash": after.get("tree_hash"),
            "change_count": 1 if changed else 0,
            "change_types": ["state_changed"] if changed else [],
            "changes": (
                [
                    {
                        "type": "state_changed",
                        "ref": "@e0",
                        "before": {"text": before.get("tree_hash")},
                        "after": {"text": after.get("tree_hash")},
                        "source_fields": ["text"],
                    }
                ]
                if changed
                else []
            ),
        }


class TestRunScenario(unittest.TestCase):
    def test_assertion_step_reuses_fixed_snapshot_and_stays_oracle_compatible(self) -> None:
        scenario = Scenario(
            name="assertion-only",
            platform="android",
            app={"android_package": "com.example.app"},
            steps=[{"action": "assert_visible", "target": "home_screen"}],
        )
        driver = _FakeDriver()

        with tempfile.TemporaryDirectory(prefix="run-scenario-assertion-") as tmp:
            run_dir = Path(tmp) / "run"
            with patch("tools.run_scenario._driver_for", return_value=driver):
                result = run_scenario._run("android", scenario, run_dir, dispatch_commands=False)

            self.assertEqual(driver.snapshot_calls, 1)
            self.assertEqual(driver.verify_calls, 1)

            step_result = result["steps"][0]
            evidence = step_result["evidence"]
            self.assertEqual(evidence["before_snapshot"], evidence["after_snapshot"])
            self.assertEqual(evidence["normalized_before"], evidence["normalized_after"])
            self.assertEqual(evidence["raw_tree_before"], evidence["raw_tree_after"])
            self.assertEqual(evidence["capture_trace_before"], evidence["capture_trace_after"])
            self.assertEqual(evidence["diff_summary"]["change_count"], 0)

            snapshot_files = sorted(path.name for path in (run_dir / "snapshots").iterdir())
            self.assertEqual(snapshot_files, ["000-before.json"])

            events = [
                json.loads(line)
                for line in (run_dir / "events.jsonl").read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            self.assertEqual([event["phase"] for event in events], ["driver", "assertion"])
            self.assertEqual(events[0]["evidence"]["before_snapshot"], events[1]["evidence"]["before_snapshot"])
            self.assertEqual(events[0]["evidence"]["after_snapshot"], events[1]["evidence"]["after_snapshot"])

            (run_dir / "run_meta.json").write_text('{"duration_seconds": 0.1}', encoding="utf-8")
            rules_path = run_dir / "rules.json"
            rules_path.write_text(
                (
                    '{"max_error_events":0,'
                    '"require_assertion_action":true,'
                    '"max_run_seconds":10,'
                    '"require_evidence_per_action":true,'
                    '"max_selector_drift_rate":1.0}'
                ),
                encoding="utf-8",
            )
            report = evaluate(run_dir, rules_path)
            self.assertTrue(report["passed"])

    def test_action_step_keeps_distinct_before_and_after_evidence(self) -> None:
        scenario = Scenario(
            name="action-only",
            platform="android",
            app={"android_package": "com.example.app"},
            steps=[{"action": "tap", "x": 10, "y": 10}],
        )
        driver = _FakeDriver()

        with tempfile.TemporaryDirectory(prefix="run-scenario-action-") as tmp:
            run_dir = Path(tmp) / "run"
            with patch("tools.run_scenario._driver_for", return_value=driver):
                result = run_scenario._run("android", scenario, run_dir, dispatch_commands=False)

            self.assertEqual(driver.snapshot_calls, 2)
            self.assertEqual(driver.verify_calls, 0)

            evidence = result["steps"][0]["evidence"]
            self.assertNotEqual(evidence["before_snapshot"], evidence["after_snapshot"])
            self.assertNotEqual(evidence["normalized_before"], evidence["normalized_after"])
            self.assertNotEqual(evidence["raw_tree_before"], evidence["raw_tree_after"])
            self.assertNotEqual(evidence["capture_trace_before"], evidence["capture_trace_after"])
            self.assertEqual(evidence["diff_summary"]["change_count"], 1)

            snapshot_files = sorted(path.name for path in (run_dir / "snapshots").iterdir())
            self.assertEqual(snapshot_files, ["000-after.json", "000-before.json"])


if __name__ == "__main__":
    unittest.main()
