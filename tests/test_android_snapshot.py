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
        self.assertEqual(
            snapshot["snapshot_request"],
            {"interactive_only": True, "compact": True, "bridge_first_full": False},
        )
        self.assertTrue(snapshot["normalization_report"]["interactive_only_applied"])
        self.assertTrue(snapshot["normalization_report"]["compact_requested"])
        self.assertFalse(snapshot["normalization_report"]["bridge_first_full_requested"])
        self.assertEqual([element["id"] for element in snapshot["elements"]], ["cta"])

    def test_bridge_first_full_snapshot_prefers_bridge_without_adb_fallback(self) -> None:
        driver = AndroidDriver(app={"android_package": "com.example.app"}, dispatch_commands=True)
        bridge_capture = {
            "status": "ok",
            "request_id": "bridge-full-1",
            "latency_ms": 9,
            "capture_trace": {"request_payload": {"interactive_only": False, "compact": False, "bridge_first_full": True}},
            "payload": {
                "protocol_version": "bridge.v1",
                "screen_id": "home_screen",
                "root": "screen.home_screen",
                "nodes": [
                    {
                        "node_id": "screen.home_screen",
                        "parent_id": None,
                        "class_name": "android.view.View",
                        "resource_id": "screen.home_screen",
                        "screen_id": "home_screen",
                        "bounds": [0, 0, 100, 100],
                        "clickable": False,
                    },
                    {
                        "node_id": "search.query_input",
                        "parent_id": "screen.home_screen",
                        "class_name": "android.widget.EditText",
                        "resource_id": "search.query_input",
                        "semantic_id": "search.query_input",
                        "screen_id": "home_screen",
                        "text": "Search",
                        "bounds": [0, 0, 50, 20],
                        "focusable": True,
                        "editable": True,
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
            raise AssertionError("ADB should not run for bridge-first full snapshot success")

        driver._adb_snapshot = unexpected_adb  # type: ignore[method-assign]

        snapshot = driver.snapshot({"interactive_only": False, "compact": False, "bridge_first_full": True})

        self.assertEqual(
            bridge_calls,
            [("com.example.app", {"interactive_only": False, "compact": False, "bridge_first_full": True})],
        )
        self.assertEqual(snapshot["capture_source"], "android_accessibility_bridge")
        self.assertEqual(
            snapshot["snapshot_request"],
            {"interactive_only": False, "compact": False, "bridge_first_full": True},
        )
        self.assertTrue(snapshot["normalization_report"]["bridge_first_full_requested"])
        self.assertEqual(snapshot["screen_id"], "home_screen")
        self.assertEqual(snapshot["elements"][1]["semantic_id"], "search.query_input")

    def test_bridge_normalization_preserves_semantic_and_screen_ids(self) -> None:
        driver = AndroidDriver(app={"android_package": "com.example.app"}, dispatch_commands=True)
        capture = {
            "status": "ok",
            "request_id": "bridge-semantic",
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
                ],
            },
        }

        snapshot = driver._normalize_bridge_snapshot(capture, {"interactive_only": False, "compact": True})

        self.assertEqual(snapshot["screen_id"], "settings")
        self.assertEqual(snapshot["elements"][0]["screen_id"], "settings")
        self.assertEqual(snapshot["elements"][1]["semantic_id"], "settings.summary_tile")
        self.assertEqual(snapshot["elements"][1]["label"], "Summary")

    def test_bridge_normalization_drops_disconnected_nodes_from_other_screens(self) -> None:
        driver = AndroidDriver(app={"android_package": "com.example.app"}, dispatch_commands=True)
        capture = {
            "status": "ok",
            "request_id": "bridge-mixed",
            "latency_ms": 7,
            "capture_trace": {"request_payload": {"interactive_only": True, "compact": True}},
            "payload": {
                "protocol_version": "bridge.v1",
                "screen_id": "search",
                "root": "screen.search",
                "nodes": [
                    {
                        "node_id": "screen.search",
                        "parent_id": None,
                        "class_name": "screen",
                        "resource_id": "screen.search",
                        "screen_id": "search",
                        "content_desc": "Search",
                        "bounds": [0, 0, 100, 100],
                    },
                    {
                        "node_id": "search.query_input",
                        "parent_id": "screen.search",
                        "class_name": "input",
                        "resource_id": "search.query_input",
                        "semantic_id": "search.query_input",
                        "screen_id": "search",
                        "text": "Search keywords",
                        "focusable": True,
                        "editable": True,
                        "bounds": [0, 0, 50, 20],
                        "index_in_parent": 0,
                    },
                    {
                        "node_id": "screen.todo_calendar",
                        "parent_id": None,
                        "class_name": "screen",
                        "resource_id": "screen.todo_calendar",
                        "screen_id": "todo_calendar",
                        "content_desc": "Todo Calendar",
                        "bounds": [0, 0, 100, 100],
                    },
                    {
                        "node_id": "todo_calendar.search_bar",
                        "parent_id": "screen.todo_calendar",
                        "class_name": "input",
                        "resource_id": "todo_calendar.search_bar",
                        "semantic_id": "todo_calendar.search_bar",
                        "screen_id": "todo_calendar",
                        "text": "Search",
                        "focusable": True,
                        "editable": True,
                        "bounds": [0, 0, 50, 20],
                        "index_in_parent": 0,
                    },
                ],
            },
        }

        snapshot = driver._normalize_bridge_snapshot(capture, {"interactive_only": True, "compact": True})

        self.assertEqual(snapshot["screen_id"], "search")
        self.assertEqual([element["screen_id"] for element in snapshot["elements"]], ["search"])
        self.assertEqual([element["id"] for element in snapshot["elements"]], ["search.query_input"])

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
        self.assertEqual(
            snapshot["snapshot_request"],
            {"interactive_only": True, "compact": True, "bridge_first_full": False},
        )
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
        self.assertEqual(
            snapshot["snapshot_request"],
            {"interactive_only": True, "compact": True, "bridge_first_full": False},
        )
        self.assertIn("bridge_snapshot", snapshot["capture_trace"])
        self.assertIn("adb_snapshot", snapshot["capture_trace"])


if __name__ == "__main__":
    unittest.main()
