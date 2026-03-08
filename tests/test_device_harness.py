from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path
from typing import Any

from harness.driver.android import AndroidDriver
from harness.evidence.bus import EvidenceBus
from harness.oracle.evaluator import evaluate


class TestDeviceHarness(unittest.TestCase):
    def test_snapshot_diff_and_verify_loop(self) -> None:
        driver = AndroidDriver(app={"android_package": "com.example.app"}, dispatch_commands=False)

        before = driver.snapshot()
        launch_result = driver.interact({"action": "launch_app"})
        after = driver.snapshot()
        diff = driver.diff(before, after)
        verify = driver.verify({"action": "assert_visible", "target": "home_screen", "timeout_ms": 200})

        self.assertIn(launch_result["status"], {"ok", "recorded"})
        self.assertEqual(before["schema_version"], "cat.v2")
        self.assertGreater(diff["change_count"], 0)
        self.assertEqual(diff["schema_version"], "cat.diff.v2")
        self.assertEqual(verify["verdict"], "pass")

    def test_verify_fails_when_expected_value_mismatches(self) -> None:
        driver = AndroidDriver(app={"android_package": "com.example.app"}, dispatch_commands=False)
        driver.interact({"action": "launch_app"})
        mismatch = driver.verify(
            {
                "action": "assert_visible",
                "target": "home_screen",
                "value": "not-home-screen",
                "timeout_ms": 100,
                "poll_ms": 50,
            }
        )

        self.assertEqual(mismatch["verdict"], "fail")
        self.assertEqual(mismatch["error_code"], "assertion_mismatch")

    def test_verify_timeout_uses_wall_clock_when_snapshot_is_slow(self) -> None:
        class SlowSnapshotDriver(AndroidDriver):
            def __init__(self, app: dict[str, str], dispatch_commands: bool) -> None:
                super().__init__(app=app, dispatch_commands=dispatch_commands)
                self.snapshot_calls = 0

            def snapshot(self, options: dict[str, Any] | None = None) -> dict[str, Any]:
                self.snapshot_calls += 1
                time.sleep(0.08)
                return super().snapshot(options)

        driver = SlowSnapshotDriver(app={"android_package": "com.example.app"}, dispatch_commands=False)

        started = time.monotonic()
        result = driver.verify({"action": "assert_visible", "target": "missing_target", "timeout_ms": 100, "poll_ms": 250})
        runtime_ms = int((time.monotonic() - started) * 1000)

        self.assertEqual(result["verdict"], "fail")
        self.assertEqual(result["error_code"], "assertion_timeout")
        self.assertLess(driver.snapshot_calls, 3)
        self.assertLess(result["elapsed_ms"], 300)
        self.assertLess(runtime_ms, 300)

    def test_selector_tap_uses_bounds_without_snapshot(self) -> None:
        class CountingDriver(AndroidDriver):
            def __init__(self, app: dict[str, str], dispatch_commands: bool) -> None:
                super().__init__(app=app, dispatch_commands=dispatch_commands)
                self.snapshot_calls = 0

            def snapshot(self, options: dict[str, Any] | None = None) -> dict[str, Any]:
                self.snapshot_calls += 1
                return super().snapshot(options)

        driver = CountingDriver(app={"android_package": "com.example.app"}, dispatch_commands=False)
        elements = [
            {
                "ref": "@e123",
                "id": "memo_button",
                "label": "Memo",
                "type": "view",
                "text": "",
                "path": "0/1",
                "ordinal": 1,
                "bounds": [10, 20, 110, 220],
            }
        ]
        result = driver.interact(
            {"action": "tap", "selector": {"by": "id", "value": "memo_button"}},
            elements=elements,
        )

        self.assertEqual(driver.snapshot_calls, 0)
        self.assertIn("input tap 60 120", result.get("command", ""))

    def test_oracle_enforces_evidence_checks(self) -> None:
        with tempfile.TemporaryDirectory(prefix="oracle-evidence-") as tmp:
            run_dir = Path(tmp)
            bus = EvidenceBus(run_dir=run_dir)
            sample_tree = {
                "schema_version": "cat.v2",
                "platform": "android",
                "elements": [],
                "tree_hash": "t1",
            }
            diff_payload = {
                "schema_version": "cat.diff.v2",
                "before_tree_hash": "t1",
                "after_tree_hash": "t2",
                "change_count": 1,
                "change_types": ["node_added"],
                "changes": [{"type": "node_added", "ref": "@e1", "before": None, "after": {}, "source_fields": []}],
            }
            before_ref = bus.write_snapshot(0, "before", sample_tree)
            after_ref = bus.write_snapshot(0, "after", dict(sample_tree, tree_hash="t2"))
            diff_ref = bus.write_diff(0, diff_payload)
            evidence = {
                "before_snapshot": before_ref,
                "after_snapshot": after_ref,
                "diff": diff_ref,
                "diff_summary": {"change_count": 1, "change_types": ["node_added"]},
            }
            bus.record_event(
                phase="driver",
                action="launch_app",
                command="echo ok",
                result={"status": "recorded"},
                step_index=0,
                evidence=evidence,
            )
            bus.record_event(
                phase="assertion",
                action="assert_visible",
                command=None,
                result={"status": "ok", "verdict": "pass"},
                step_index=0,
                evidence=evidence,
            )
            bus.finalize(extra={"platform": "android"})
            (run_dir / "run_meta.json").write_text('{"duration_seconds": 1}', encoding="utf-8")

            rules_path = run_dir / "rules.json"
            rules_path.write_text(
                (
                    '{"max_error_events":0,'
                    '"require_assertion_action":true,'
                    '"max_run_seconds":10,'
                    '"require_evidence_per_action":true,'
                    '"max_selector_drift_rate":1.0,'
                    '"require_structural_change_for_actions":["launch_app"]}'
                ),
                encoding="utf-8",
            )
            report = evaluate(run_dir, rules_path)
            self.assertTrue(report["passed"])


if __name__ == "__main__":
    unittest.main()
