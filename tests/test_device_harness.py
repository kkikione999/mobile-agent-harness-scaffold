from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

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
        self.assertGreater(diff["change_count"], 0)
        self.assertEqual(verify["verdict"], "pass")

    def test_oracle_enforces_evidence_checks(self) -> None:
        with tempfile.TemporaryDirectory(prefix="oracle-evidence-") as tmp:
            run_dir = Path(tmp)
            bus = EvidenceBus(run_dir=run_dir)
            sample_tree = {
                "schema_version": "cat.v1",
                "platform": "android",
                "elements": [],
                "tree_hash": "t1",
            }
            diff_payload = {
                "schema_version": "cat.diff.v1",
                "before_tree_hash": "t1",
                "after_tree_hash": "t2",
                "change_count": 1,
                "change_types": ["node_added"],
                "changes": [{"type": "node_added", "ref": "@e1"}],
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
