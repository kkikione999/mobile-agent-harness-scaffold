from __future__ import annotations

import unittest

from harness.driver.android import AndroidDriver


class TestAndroidSnapshot(unittest.TestCase):
    def test_lightweight_snapshot_prefers_bridge_and_preserves_operability_root(self) -> None:
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
                        "node_id": "content",
                        "parent_id": "root",
                        "class_name": "android.view.ViewGroup",
                        "resource_id": "content",
                        "content_desc": "Content",
                        "bounds": [0, 0, 100, 100],
                        "clickable": False,
                        "index_in_parent": 0,
                    },
                    {
                        "node_id": "cta",
                        "parent_id": "content",
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
        self.assertEqual(snapshot["snapshot_health"]["status"], "healthy")
        self.assertEqual(snapshot["snapshot_request"], {"interactive_only": True, "compact": True})
        self.assertTrue(snapshot["normalization_report"]["interactive_only_applied"])
        self.assertEqual(snapshot["normalization_report"]["interactive_only_mode"], "projection")
        self.assertTrue(snapshot["normalization_report"]["compact_requested"])
        self.assertTrue(snapshot["normalization_report"]["authoritative_root_preserved"])
        self.assertEqual(snapshot["root"], snapshot["elements"][0]["ref"])
        self.assertEqual([element["id"] for element in snapshot["elements"]], ["root", "content", "cta"])
        self.assertEqual(snapshot["interactive_projection"]["authoritative_root"], snapshot["root"])
        self.assertEqual(snapshot["interactive_projection"]["element_ids"], ["cta"])
        self.assertEqual(snapshot["interactive_projection"]["root"], snapshot["elements"][-1]["ref"])

    def test_bridge_normalization_keeps_only_the_active_scope_for_mixed_screens(self) -> None:
        driver = AndroidDriver(app={"android_package": "com.example.app"}, dispatch_commands=True)
        capture = {
            "status": "ok",
            "request_id": "bridge-mixed-scope",
            "latency_ms": 7,
            "capture_trace": {"request_payload": {"interactive_only": False, "compact": True}},
            "payload": {
                "protocol_version": "bridge.v1",
                "screen_id": "settings",
                "root": "screen.settings",
                "nodes": [
                    {
                        "node_id": "screen.settings",
                        "parent_id": None,
                        "class_name": "android.view.View",
                        "resource_id": "screen.settings",
                        "screen_id": "settings",
                        "label": "Settings",
                        "content_desc": "Settings",
                        "bounds": [0, 0, 100, 100],
                        "clickable": False,
                    },
                    {
                        "node_id": "settings.summary_tile",
                        "parent_id": "screen.settings",
                        "class_name": "android.widget.Button",
                        "resource_id": "settings.summary_tile",
                        "semantic_id": "settings.summary_tile",
                        "screen_id": "settings",
                        "label": "Summary",
                        "text": "Summary",
                        "bounds": [0, 0, 50, 20],
                        "clickable": True,
                        "index_in_parent": 0,
                    },
                    {
                        "node_id": "screen.profile",
                        "parent_id": None,
                        "class_name": "android.view.View",
                        "resource_id": "screen.profile",
                        "screen_id": "profile",
                        "label": "Profile",
                        "content_desc": "Profile",
                        "bounds": [0, 0, 100, 100],
                        "clickable": False,
                    },
                    {
                        "node_id": "profile.edit_button",
                        "parent_id": "screen.profile",
                        "class_name": "android.widget.Button",
                        "resource_id": "profile.edit_button",
                        "semantic_id": "profile.edit_button",
                        "screen_id": "profile",
                        "label": "Edit",
                        "text": "Edit",
                        "bounds": [0, 0, 50, 20],
                        "clickable": True,
                        "index_in_parent": 0,
                    },
                ],
            },
        }

        snapshot = driver._normalize_bridge_snapshot(capture, {"interactive_only": False, "compact": True})

        self.assertEqual(snapshot["snapshot_health"]["status"], "healthy")
        self.assertEqual(snapshot["screen_id"], "settings")
        self.assertEqual([element["id"] for element in snapshot["elements"]], ["screen.settings", "settings.summary_tile"])
        self.assertEqual(snapshot["elements"][0]["screen_id"], "settings")
        self.assertEqual(snapshot["elements"][1]["semantic_id"], "settings.summary_tile")
        self.assertEqual(snapshot["elements"][1]["label"], "Summary")
        self.assertEqual(snapshot["normalization_report"]["active_scope_screen_id"], "settings")
        self.assertEqual(snapshot["normalization_report"]["dropped_out_of_scope_nodes"], 2)

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
        self.assertEqual(snapshot["snapshot_health"]["status"], "degraded")
        self.assertEqual(snapshot["snapshot_health"]["reason"], "bridge_unreachable")
        self.assertEqual(snapshot["capture_error"]["error_code"], "bridge_unreachable")
        self.assertEqual(snapshot["snapshot_request"], {"interactive_only": True, "compact": True})
        self.assertEqual(snapshot["root"], snapshot["elements"][0]["ref"])
        self.assertEqual([element["id"] for element in snapshot["elements"]], ["root", "cta"])
        self.assertEqual(snapshot["interactive_projection"]["element_ids"], ["cta"])
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
        self.assertEqual(snapshot["snapshot_health"]["status"], "degraded")
        self.assertEqual(snapshot["snapshot_health"]["reason"], "bridge_timeout")
        self.assertEqual(snapshot["capture_error"]["error_code"], "bridge_timeout")
        self.assertEqual(snapshot["capture_error"]["adb_error_code"], "adb_timeout")
        self.assertEqual(snapshot["snapshot_request"], {"interactive_only": True, "compact": True})
        self.assertIn("bridge_snapshot", snapshot["capture_trace"])
        self.assertIn("adb_snapshot", snapshot["capture_trace"])


if __name__ == "__main__":
    unittest.main()
