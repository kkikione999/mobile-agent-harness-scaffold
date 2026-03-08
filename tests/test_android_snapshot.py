from __future__ import annotations

import unittest

from harness.driver.android import AndroidDriver


class TestAndroidSnapshot(unittest.TestCase):
    def test_lightweight_snapshot_prefers_bridge_and_applies_request_options(self) -> None:
        driver = AndroidDriver(app={"android_package": "com.example.app"}, dispatch_commands=True)
        bridge_capture = {
            "status": "ok",
            "request_id": "bridge-1",
            "latency_ms": 7,
            "capture_trace": {"request_payload": {"interactive_only": True, "compact": True}},
            "payload": {
                "protocol_version": "bridge.v1",
                "root": "root",
                "nodes": [
                    {
                        "node_id": "root",
                        "parent_id": None,
                        "class_name": "android.widget.FrameLayout",
                        "resource_id": "root",
                        "content_desc": "Root",
                        "bounds": [0, 0, 100, 100],
                        "clickable": False,
                    },
                    {
                        "node_id": "cta",
                        "parent_id": "root",
                        "class_name": "android.widget.Button",
                        "resource_id": "cta",
                        "text": "Continue",
                        "bounds": [0, 0, 50, 20],
                        "clickable": True,
                        "index_in_parent": 0,
                    },
                ],
            },
        }

        bridge_calls: list[tuple[str, dict[str, bool]]] = []

        def bridge_snapshot(*, app_package: str, options: dict[str, bool]) -> dict[str, object]:
            bridge_calls.append((app_package, dict(options)))
            return bridge_capture

        driver._bridge.snapshot = bridge_snapshot  # type: ignore[method-assign]

        def unexpected_adb() -> dict[str, object]:
            raise AssertionError("ADB should not run for lightweight bridge success")

        driver._adb_snapshot = unexpected_adb  # type: ignore[method-assign]

        snapshot = driver.snapshot({"interactive_only": True, "compact": True})

        self.assertEqual(bridge_calls, [("com.example.app", {"interactive_only": True, "compact": True})])
        self.assertEqual(snapshot["capture_source"], "android_accessibility_bridge")
        self.assertEqual(snapshot["snapshot_request"], {"interactive_only": True, "compact": True})
        self.assertTrue(snapshot["normalization_report"]["interactive_only_applied"])
        self.assertTrue(snapshot["normalization_report"]["compact_requested"])
        self.assertEqual([element["id"] for element in snapshot["elements"]], ["cta"])

    def test_lightweight_snapshot_falls_back_to_adb_explicitly(self) -> None:
        driver = AndroidDriver(app={"android_package": "com.example.app"}, dispatch_commands=True)
        calls: list[str] = []

        def bridge_snapshot(*, app_package: str, options: dict[str, bool]) -> dict[str, object]:
            _ = (app_package, options)
            calls.append("bridge")
            return {
                "status": "error",
                "request_id": "bridge-2",
                "error_code": "bridge_unreachable",
                "details": "connection refused",
                "bridge_status": "error",
                "bridge_error_code": "bridge_unreachable",
                "bridge_http_status": None,
                "capture_trace": {"request_id": "bridge-2"},
                "payload": None,
            }

        def adb_snapshot() -> dict[str, object]:
            calls.append("adb")
            return {
                "status": "ok",
                "request_id": "adb-1",
                "xml": (
                    '<hierarchy>'
                    '<node class="android.widget.FrameLayout" resource-id="root" clickable="false" bounds="[0,0][100,100]">'
                    '<node class="android.widget.Button" resource-id="cta" text="Continue" clickable="true" bounds="[0,0][50,20]" />'
                    '</node>'
                    '</hierarchy>'
                ),
            }

        driver._bridge.snapshot = bridge_snapshot  # type: ignore[method-assign]
        driver._adb_snapshot = adb_snapshot  # type: ignore[method-assign]

        snapshot = driver.snapshot({"interactive_only": True, "compact": True})

        self.assertEqual(calls, ["bridge", "adb"])
        self.assertEqual(snapshot["capture_source"], "adb_uiautomator_fallback")
        self.assertEqual(snapshot["capture_error"]["error_code"], "bridge_unreachable")
        self.assertEqual(snapshot["snapshot_request"], {"interactive_only": True, "compact": True})
        self.assertEqual([element["id"] for element in snapshot["elements"]], ["cta"])
        self.assertIn("bridge_snapshot", snapshot["capture_trace"])

    def test_lightweight_snapshot_uses_synthetic_fallback_when_bridge_and_adb_fail(self) -> None:
        driver = AndroidDriver(app={"android_package": "com.example.app"}, dispatch_commands=True)

        driver._bridge.snapshot = lambda *, app_package, options: {  # type: ignore[method-assign]
            "status": "error",
            "request_id": "bridge-3",
            "error_code": "bridge_timeout",
            "details": "bridge request timed out",
            "bridge_status": "error",
            "bridge_error_code": "bridge_timeout",
            "bridge_http_status": None,
            "capture_trace": {"request_id": "bridge-3"},
            "payload": None,
            "latency_ms": 10,
        }
        driver._adb_snapshot = lambda: {  # type: ignore[method-assign]
            "status": "error",
            "error_code": "adb_timeout",
            "details": "ADB command timed out",
        }

        snapshot = driver.snapshot({"interactive_only": True, "compact": True})

        self.assertEqual(snapshot["capture_source"], "bridge_error_fallback")
        self.assertEqual(snapshot["capture_error"]["error_code"], "bridge_timeout")
        self.assertEqual(snapshot["capture_error"]["adb_error_code"], "adb_timeout")
        self.assertEqual(snapshot["snapshot_request"], {"interactive_only": True, "compact": True})
        self.assertIn("bridge_snapshot", snapshot["capture_trace"])
        self.assertIn("adb_snapshot", snapshot["capture_trace"])


if __name__ == "__main__":
    unittest.main()
