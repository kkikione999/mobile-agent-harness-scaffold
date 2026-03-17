from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

from harness.driver.device_bridge import DeviceHarness
from tools import mcp_server


class _FakeRunner:
    def __init__(self, result: mcp_server.CommandResult):
        self.result = result
        self.commands: list[list[str]] = []
        self.env_overrides: list[dict[str, str] | None] = []

    def __call__(self, command: list[str], env_overrides: dict[str, str] | None = None) -> mcp_server.CommandResult:
        self.commands.append(command)
        self.env_overrides.append(env_overrides)
        return self.result


class _FailRunner:
    def __call__(self, command: list[str], env_overrides: dict[str, str] | None = None) -> mcp_server.CommandResult:
        _ = (command, env_overrides)
        raise AssertionError("subprocess runner should not be used for device_* tools")


class _RecordingDriver:
    def __init__(self, app: dict[str, Any], dispatch_commands: bool) -> None:
        self.app = app
        self.dispatch_commands = dispatch_commands
        self.snapshot_calls: list[dict[str, bool]] = []
        self.raw_snapshot_calls: list[dict[str, Any]] = []
        self.state: dict[str, Any] = {}

    def preflight(self) -> dict[str, Any]:
        return {"status": "ok"}

    def interact(self, action: dict[str, Any], elements: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        _ = elements
        if action.get("action") == "launch_app":
            return {"status": "ok"}
        return {"status": "ok", "action": action.get("action")}

    def snapshot(self, options: dict[str, Any] | None = None) -> dict[str, Any]:
        self.raw_snapshot_calls.append(dict(options or {}))
        resolved = {
            "interactive_only": bool((options or {}).get("interactive_only", False)),
            "compact": bool((options or {}).get("compact", False)),
        }
        self.snapshot_calls.append(resolved)
        suffix = f"{int(resolved['interactive_only'])}:{int(resolved['compact'])}"
        elements = [
            {
                "id": "screen.home_screen",
                "screen_id": "home_screen",
                "label": "Home Screen",
                "ref": "@screen-home",
                "resource_id": "screen.home_screen",
                "text": "Home Screen",
                "content_desc": "home screen",
                "class_name": "android.view.View",
                "type": "screen",
                "interactive": False,
                "enabled": True,
                "visible": True,
                "bounds": [0, 0, 100, 100],
                "path": "0",
            },
            {
                "id": f"search_box_{suffix}",
                "screen_id": "home_screen",
                "semantic_id": "search.query_input",
                "label": "Search Box",
                "ref": f"@e-{suffix}",
                "resource_id": f"search_box_{suffix}",
                "text": "",
                "content_desc": "search box",
                "class_name": "android.widget.EditText",
                "type": "input",
                "interactive": True,
                "enabled": True,
                "visible": True,
                "bounds": [0, 0, 100, 40],
                "path": "0/0",
            }
        ]
        return {
            "schema_version": "cat.v2",
            "tree_hash": suffix,
            "root": "@screen-home",
            "screen_id": "home_screen",
            "elements": elements,
            "options": resolved,
            "element_map": {element["id"]: element["ref"] for element in elements},
            "capture_source": "synthetic_state_model",
            "capture_trace": {"details": "x" * 256},
        }

    def dump_state(self) -> dict[str, Any]:
        return dict(self.state)

    def restore_state(self, state: dict[str, Any]) -> None:
        self.state = dict(state)

    def verify(self, assertion: dict[str, Any]) -> dict[str, Any]:
        return {"status": "ok", "verdict": "pass", "assertion": assertion}


class _SemanticRecordingDriver(_RecordingDriver):
    def snapshot(self, options: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = super().snapshot(options)
        payload["capture_source"] = "android_accessibility_bridge"
        payload["screen_id"] = "home_screen"
        payload["elements"][0]["screen_id"] = "home_screen"
        payload["elements"][1]["screen_id"] = "home_screen"
        payload["elements"][1]["semantic_id"] = "search.query_input"
        payload["elements"] = [payload["elements"][1], payload["elements"][0]]
        return payload


class _FallbackRecordingDriver(_RecordingDriver):
    def snapshot(self, options: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = super().snapshot(options)
        payload["capture_source"] = "adb_uiautomator_fallback"
        payload["capture_error"] = {"error_code": "bridge_http_error", "details": "bridge returned 502"}
        payload["screen_id"] = None
        payload["elements"][0]["screen_id"] = None
        payload["elements"][1]["screen_id"] = None
        payload["elements"][1].pop("semantic_id", None)
        return payload


class _SelectorDriftRetryDriver(_SemanticRecordingDriver):
    def interact(self, action: dict[str, Any], elements: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        selector = action.get("selector") or {}
        selector_value = str(selector.get("value", ""))
        if action.get("action") == "launch_app":
            return {"status": "ok"}
        if elements and any(str(item.get("id", "")) == selector_value for item in elements if isinstance(item, dict)):
            return {"status": "ok", "action": action.get("action"), "selector": selector_value}
        return {
            "status": "error",
            "error_code": "selector_drift",
            "details": "selector not found in cached elements",
        }

    def snapshot(self, options: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = super().snapshot(options)
        if not bool((options or {}).get("interactive_only", False)):
            payload["elements"].append(
                {
                    "id": "search.query_input",
                    "screen_id": "home_screen",
                    "semantic_id": "search.query_input",
                    "label": "Search keywords",
                    "ref": "@e-search-real",
                    "resource_id": "search.query_input",
                    "text": "Search keywords",
                    "content_desc": "Search keywords",
                    "class_name": "android.widget.EditText",
                    "type": "input",
                    "interactive": True,
                    "enabled": True,
                    "visible": True,
                    "bounds": [0, 0, 100, 40],
                    "path": "0/9",
                }
            )
        return payload


class _SelectorDriftFallbackDriver(_SelectorDriftRetryDriver):
    def snapshot(self, options: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = super().snapshot(options)
        if not bool((options or {}).get("interactive_only", False)):
            payload["capture_source"] = "adb_uiautomator_fallback"
            payload["capture_error"] = {"error_code": "bridge_http_error", "details": "bridge returned 502"}
            payload["screen_id"] = None
            for element in payload["elements"]:
                if isinstance(element, dict):
                    element["screen_id"] = None
                    element.pop("semantic_id", None)
        return payload


class _NeverSettlesDriver(_SemanticRecordingDriver):
    def __init__(self, app: dict[str, Any], dispatch_commands: bool) -> None:
        super().__init__(app=app, dispatch_commands=dispatch_commands)
        self._unstable = False
        self._unstable_counter = 0

    def interact(self, action: dict[str, Any], elements: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        _ = elements
        self._unstable = action.get("action") in {"launch_app", "tap", "input_text"}
        return {"status": "ok", "action": action.get("action")}

    def snapshot(self, options: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = super().snapshot(options)
        if self._unstable:
            self._unstable_counter += 1
            payload["tree_hash"] = f"unstable-{self._unstable_counter}"
        return payload


class _WarmLaunchSemanticRecoveryDriver(_SemanticRecordingDriver):
    def __init__(self, app: dict[str, Any], dispatch_commands: bool) -> None:
        super().__init__(app=app, dispatch_commands=dispatch_commands)
        self._full_snapshot_attempts = 0

    def preflight(self) -> dict[str, Any]:
        return {"status": "ok", "bridge": {"status": "healthy"}}

    def _fallback_snapshot(self, options: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = _RecordingDriver.snapshot(self, options)
        payload["capture_source"] = "adb_uiautomator_fallback"
        payload["capture_error"] = {"error_code": "bridge_http_error", "details": "bridge returned 502"}
        payload["screen_id"] = None
        payload["elements"][0]["screen_id"] = None
        payload["elements"][1]["screen_id"] = None
        payload["elements"][1].pop("semantic_id", None)
        return payload

    def snapshot(self, options: dict[str, Any] | None = None) -> dict[str, Any]:
        resolved = {
            "interactive_only": bool((options or {}).get("interactive_only", False)),
            "compact": bool((options or {}).get("compact", False)),
        }
        if resolved["interactive_only"] or resolved["compact"]:
            return self._fallback_snapshot(options)

        self._full_snapshot_attempts += 1
        if self._full_snapshot_attempts < 2:
            payload = self._fallback_snapshot(options)
            payload["tree_hash"] = f"warm-fallback-{self._full_snapshot_attempts}"
            return payload

        payload = _SemanticRecordingDriver.snapshot(self, options)
        payload["tree_hash"] = "screen.settings"
        payload["root"] = "@screen-settings"
        payload["screen_id"] = "screen.settings"
        for element in payload["elements"]:
            if isinstance(element, dict):
                element["screen_id"] = "screen.settings"

        screen = next((element for element in payload["elements"] if isinstance(element, dict) and element.get("type") == "screen"), None)
        if isinstance(screen, dict):
            screen["id"] = "screen.settings"
            screen["ref"] = "@screen-settings"
            screen["resource_id"] = "screen.settings"
            screen["label"] = "Settings"
            screen["text"] = "Settings"
            screen["content_desc"] = "settings"
        return payload

    def wait_for_state_settle(
        self,
        *,
        timeout_ms: int,
        poll_ms: int,
        stable_observations: int,
        snapshot_options: dict[str, Any],
    ) -> dict[str, Any]:
        _ = poll_ms
        degraded = self._fallback_snapshot(snapshot_options)
        degraded["tree_hash"] = "warm-launch-degraded"
        return {
            "status": "timeout",
            "attempts": 1,
            "elapsed_ms": timeout_ms,
            "stable_observations": stable_observations,
            "tree_hash": degraded.get("tree_hash"),
            "screen_id": degraded.get("screen_id"),
            "root": degraded.get("root"),
            "snapshot": degraded,
        }


class _PostActionSemanticSettlementDriver(_WarmLaunchSemanticRecoveryDriver):
    def __init__(self, app: dict[str, Any], dispatch_commands: bool) -> None:
        super().__init__(app=app, dispatch_commands=dispatch_commands)
        self.wait_for_state_settle_calls = 0

    def wait_for_state_settle(
        self,
        *,
        timeout_ms: int,
        poll_ms: int,
        stable_observations: int,
        snapshot_options: dict[str, Any],
    ) -> dict[str, Any]:
        _ = (poll_ms, stable_observations)
        self.wait_for_state_settle_calls += 1
        degraded = self._fallback_snapshot(snapshot_options)
        degraded["tree_hash"] = "post-action-degraded"
        return {
            "status": "settled",
            "attempts": 1,
            "elapsed_ms": timeout_ms,
            "stable_observations": 1,
            "tree_hash": degraded.get("tree_hash"),
            "screen_id": degraded.get("screen_id"),
            "root": degraded.get("root"),
            "snapshot": degraded,
        }


class _AmbiguousSelectorDriver(DeviceHarness):
    def __init__(self, app: dict[str, Any], dispatch_commands: bool) -> None:
        super().__init__(platform="android", app=app, dispatch_commands=dispatch_commands)

    def command_for_action(self, action: dict[str, Any]) -> str | None:
        if action.get("action") == "launch_app":
            return "launch"
        if action.get("action") == "tap":
            return "tap"
        if action.get("action") == "input_text":
            return "input"
        return None

    def app_identity(self) -> str:
        return str(self.app.get("android_package", "com.example.app"))

    def snapshot(self, options: dict[str, Any] | None = None) -> dict[str, Any]:
        _ = options
        elements = [
            {
                "ref": "@e-root",
                "id": "root",
                "label": "Root",
                "text": "",
                "path": "0",
                "ordinal": 0,
                "interactive": False,
                "class_name": "root",
                "resource_id": "root",
                "content_desc": "root",
                "bounds": [0, 0, 100, 100],
                "clickable": False,
                "enabled": True,
                "visible": True,
                "focusable": False,
                "checked": False,
                "selected": False,
                "editable": False,
                "depth": 0,
                "index_in_parent": 0,
                "source_node_id": "root",
                "type": "root",
            },
            {
                "ref": "@e-save-a",
                "id": "save",
                "label": "Save",
                "text": "Save",
                "path": "0/1",
                "ordinal": 1,
                "interactive": True,
                "class_name": "android.widget.Button",
                "resource_id": "save",
                "content_desc": "save",
                "bounds": [0, 0, 40, 20],
                "clickable": True,
                "enabled": True,
                "visible": True,
                "focusable": False,
                "checked": False,
                "selected": False,
                "editable": False,
                "depth": 1,
                "index_in_parent": 1,
                "source_node_id": "save-a",
                "type": "button",
            },
            {
                "ref": "@e-save-b",
                "id": "save",
                "label": "Save",
                "text": "Save",
                "path": "0/2",
                "ordinal": 2,
                "interactive": True,
                "class_name": "android.widget.Button",
                "resource_id": "save",
                "content_desc": "save",
                "bounds": [50, 0, 90, 20],
                "clickable": True,
                "enabled": True,
                "visible": True,
                "focusable": False,
                "checked": False,
                "selected": False,
                "editable": False,
                "depth": 1,
                "index_in_parent": 2,
                "source_node_id": "save-b",
                "type": "button",
            },
        ]
        return {
            "schema_version": "cat.v2",
            "tree_hash": "ambiguous-save",
            "elements": elements,
            "element_map": {"save": "@e-save-a"},
        }


class TestMCPServer(unittest.TestCase):
    def setUp(self) -> None:
        mcp_server.DEVICE_SESSION_CACHE.clear()

    def _assert_post_action_settlement_stays_semantic(
        self,
        *,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> None:
        with tempfile.TemporaryDirectory(prefix=f"mcp-{tool_name}-semantic-settle-") as tmp:
            session_file = str(Path(tmp) / "session.json")
            server = mcp_server.MCPServer(runner=_FailRunner())
            driver = _PostActionSemanticSettlementDriver(
                app={"android_package": "com.example.app"},
                dispatch_commands=False,
            )

            with mock.patch("tools.mcp_server._build_device_driver", return_value=driver):
                open_response = server.handle_message(
                    {
                        "jsonrpc": "2.0",
                        "id": 127,
                        "method": "tools/call",
                        "params": {
                            "name": "device_open",
                            "arguments": {
                                "platform": "android",
                                "app": "com.example.app",
                                "dispatch_commands": False,
                                "session_file": session_file,
                            },
                        },
                    }
                )
                self.assertIsNotNone(open_response)
                self.assertFalse(open_response["result"]["isError"])  # type: ignore[index]

                driver.raw_snapshot_calls.clear()

                action_response = server.handle_message(
                    {
                        "jsonrpc": "2.0",
                        "id": 128,
                        "method": "tools/call",
                        "params": {
                            "name": tool_name,
                            "arguments": {"session_file": session_file, **arguments},
                        },
                    }
                )

            self.assertIsNotNone(action_response)
            self.assertFalse(action_response["result"]["isError"])  # type: ignore[index]
            result_json = action_response["result"]["structuredContent"]["result_json"]  # type: ignore[index]
            self.assertEqual(result_json["status"], "ok")
            self.assertEqual(result_json["settlement"]["status"], "settled")
            self.assertEqual(result_json["settlement"]["screen_id"], "screen.settings")
            self.assertTrue(result_json["settlement"]["snapshot"]["live_semantics_ready"])
            self.assertFalse(result_json["settlement"]["degraded"])
            self.assertEqual(driver.wait_for_state_settle_calls, 0)
            self.assertEqual(
                driver.raw_snapshot_calls,
                [
                    {"interactive_only": False, "compact": False, "bridge_first_full": True},
                    {"interactive_only": False, "compact": False, "bridge_first_full": True},
                ],
            )

    def test_tools_list_contains_core_tools(self) -> None:
        server = mcp_server.MCPServer()
        response = server.handle_message({"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}})
        self.assertIsNotNone(response)

        payload = response["result"]["tools"]  # type: ignore[index]
        names = {tool["name"] for tool in payload}
        self.assertIn("run_scenario", names)
        self.assertIn("evaluate_run", names)
        self.assertIn("device_open", names)
        self.assertIn("device_list", names)
        self.assertIn("device_find", names)
        self.assertIn("device_page_map", names)
        self.assertIn("device_element_dictionary", names)

    def test_run_scenario_tool_call_maps_to_script_and_parses_run_dir(self) -> None:
        runner = _FakeRunner(
            mcp_server.CommandResult(
                returncode=0,
                stdout="run complete: runs/20260302T010203Z-cold_start_android\n",
                stderr="",
            )
        )
        server = mcp_server.MCPServer(runner=runner)
        message = {
            "jsonrpc": "2.0",
            "id": 9,
            "method": "tools/call",
            "params": {
                "name": "run_scenario",
                "arguments": {
                    "scenario": "scenarios/smoke/cold_start_android.json",
                    "platform": "android",
                    "dispatch_commands": True,
                },
            },
        }
        response = server.handle_message(message)
        self.assertIsNotNone(response)
        result = response["result"]  # type: ignore[index]

        self.assertFalse(result["isError"])
        structured = result["structuredContent"]
        self.assertEqual(structured["run_dir"], "runs/20260302T010203Z-cold_start_android")
        self.assertEqual(runner.env_overrides[0], {"DISPATCH_COMMANDS": "1"})
        self.assertTrue(runner.commands[0][-1].endswith("android"))

    def test_invalid_tool_arguments_return_jsonrpc_error(self) -> None:
        server = mcp_server.MCPServer()
        message: dict[str, Any] = {
            "jsonrpc": "2.0",
            "id": 12,
            "method": "tools/call",
            "params": {"name": "run_scenario", "arguments": {"platform": "android"}},
        }
        response = server.handle_message(message)
        self.assertIsNotNone(response)

        error = response["error"]  # type: ignore[index]
        self.assertEqual(error["code"], -32602)
        self.assertIn("scenario", error["message"])

    def test_device_flow_uses_in_process_session(self) -> None:
        with tempfile.TemporaryDirectory(prefix="mcp-device-") as tmp:
            session_file = str(Path(tmp) / "session.json")
            server = mcp_server.MCPServer(runner=_FailRunner())

            open_response = server.handle_message(
                {
                    "jsonrpc": "2.0",
                    "id": 20,
                    "method": "tools/call",
                    "params": {
                        "name": "device_open",
                        "arguments": {
                            "platform": "android",
                            "app": "com.example.app",
                            "dispatch_commands": False,
                            "session_file": session_file,
                        },
                    },
                }
            )
            self.assertIsNotNone(open_response)
            self.assertFalse(open_response["result"]["isError"])  # type: ignore[index]

            snapshot_response = server.handle_message(
                {
                    "jsonrpc": "2.0",
                    "id": 21,
                    "method": "tools/call",
                    "params": {
                        "name": "device_snapshot",
                        "arguments": {"session_file": session_file, "interactive": True, "compact": True},
                    },
                }
            )
            self.assertIsNotNone(snapshot_response)
            snapshot = snapshot_response["result"]["structuredContent"]["result_json"]  # type: ignore[index]
            self.assertEqual(snapshot["schema_version"], "cat.v2")

            list_response = server.handle_message(
                {
                    "jsonrpc": "2.0",
                    "id": 215,
                    "method": "tools/call",
                    "params": {"name": "device_list", "arguments": {"session_file": session_file}},
                }
            )
            self.assertIsNotNone(list_response)
            list_structured = list_response["result"]["structuredContent"]  # type: ignore[index]
            elements = list_structured["result_json"]
            self.assertIsInstance(elements, list)
            self.assertTrue(elements)
            for field in ("id", "label", "ref", "resource_id", "text", "bounds", "path"):
                self.assertIn(field, elements[0])
            self.assertTrue(any(el.get("id") == "search_box" for el in elements))
            self.assertTrue(list_structured["cache_hit"])

            find_response = server.handle_message(
                {
                    "jsonrpc": "2.0",
                    "id": 216,
                    "method": "tools/call",
                    "params": {
                        "name": "device_find",
                        "arguments": {"session_file": session_file, "query": "search", "field": "id"},
                    },
                }
            )
            self.assertIsNotNone(find_response)
            find_structured = find_response["result"]["structuredContent"]  # type: ignore[index]
            matches = find_structured["result_json"]
            self.assertTrue(find_structured["cache_hit"])
            self.assertTrue(matches)
            self.assertEqual(matches[0]["id"], "search_box")

            fill_response = server.handle_message(
                {
                    "jsonrpc": "2.0",
                    "id": 22,
                    "method": "tools/call",
                    "params": {
                        "name": "device_fill",
                        "arguments": {"session_file": session_file, "element": "search_box", "text": "i am here"},
                    },
                }
            )
            self.assertIsNotNone(fill_response)
            self.assertFalse(fill_response["result"]["isError"])  # type: ignore[index]

            verify_response = server.handle_message(
                {
                    "jsonrpc": "2.0",
                    "id": 23,
                    "method": "tools/call",
                    "params": {
                        "name": "device_verify",
                        "arguments": {
                            "session_file": session_file,
                            "element": "search_box",
                            "expected": "i am here",
                            "timeout_ms": 100,
                        },
                    },
                }
            )
            self.assertIsNotNone(verify_response)
            verify_result = verify_response["result"]["structuredContent"]["result_json"]["result"]  # type: ignore[index]
            self.assertEqual(verify_result["verdict"], "pass")

    def test_device_session_persistence_round_trip(self) -> None:
        with tempfile.TemporaryDirectory(prefix="mcp-device-persist-") as tmp:
            session_file = str(Path(tmp) / "session.json")
            server = mcp_server.MCPServer(runner=_FailRunner())
            open_response = server.handle_message(
                {
                    "jsonrpc": "2.0",
                    "id": 30,
                    "method": "tools/call",
                    "params": {
                        "name": "device_open",
                        "arguments": {
                            "platform": "android",
                            "app": "com.example.app",
                            "dispatch_commands": False,
                            "session_file": session_file,
                            "persist_session": True,
                        },
                    },
                }
            )
            self.assertIsNotNone(open_response)
            self.assertTrue(Path(session_file).exists())

            mcp_server.DEVICE_SESSION_CACHE.clear()
            snapshot_response = server.handle_message(
                {
                    "jsonrpc": "2.0",
                    "id": 31,
                    "method": "tools/call",
                    "params": {"name": "device_snapshot", "arguments": {"session_file": session_file}},
                }
            )
            self.assertIsNotNone(snapshot_response)
            self.assertFalse(snapshot_response["result"]["isError"])  # type: ignore[index]

    def test_device_snapshot_defaults_to_lightweight_options(self) -> None:
        with tempfile.TemporaryDirectory(prefix="mcp-device-defaults-") as tmp:
            session_file = str(Path(tmp) / "session.json")
            driver = _RecordingDriver(app={"android_package": "com.example.app"}, dispatch_commands=False)
            server = mcp_server.MCPServer(runner=_FailRunner())

            with mock.patch("tools.mcp_server._build_device_driver", return_value=driver):
                open_response = server.handle_message(
                    {
                        "jsonrpc": "2.0",
                        "id": 50,
                        "method": "tools/call",
                        "params": {
                            "name": "device_open",
                            "arguments": {
                                "platform": "android",
                                "app": "com.example.app",
                                "dispatch_commands": False,
                                "session_file": session_file,
                            },
                        },
                    }
                )
                self.assertIsNotNone(open_response)
                mcp_server.DEVICE_SESSION_CACHE[session_file].snapshot_cache.clear()
                driver.snapshot_calls.clear()

                snapshot_response = server.handle_message(
                    {
                        "jsonrpc": "2.0",
                        "id": 51,
                        "method": "tools/call",
                        "params": {"name": "device_snapshot", "arguments": {"session_file": session_file}},
                    }
                )

            self.assertIsNotNone(snapshot_response)
            self.assertEqual(driver.snapshot_calls, [{"interactive_only": True, "compact": True}])
            structured = snapshot_response["result"]["structuredContent"]  # type: ignore[index]
            self.assertEqual(structured["snapshot_options"], {"interactive": True, "compact": True})
            self.assertEqual(structured["result_json"]["options"], {"interactive_only": True, "compact": True})

    def test_device_snapshot_cache_is_keyed_by_option_tuple(self) -> None:
        with tempfile.TemporaryDirectory(prefix="mcp-device-cache-") as tmp:
            session_file = str(Path(tmp) / "session.json")
            driver = _RecordingDriver(app={"android_package": "com.example.app"}, dispatch_commands=False)
            server = mcp_server.MCPServer(runner=_FailRunner())

            with mock.patch("tools.mcp_server._build_device_driver", return_value=driver):
                open_response = server.handle_message(
                    {
                        "jsonrpc": "2.0",
                        "id": 60,
                        "method": "tools/call",
                        "params": {
                            "name": "device_open",
                            "arguments": {
                                "platform": "android",
                                "app": "com.example.app",
                                "dispatch_commands": False,
                                "session_file": session_file,
                            },
                        },
                    }
                )
                self.assertIsNotNone(open_response)
                mcp_server.DEVICE_SESSION_CACHE[session_file].snapshot_cache.clear()
                driver.snapshot_calls.clear()

                default_snapshot_1 = server.handle_message(
                    {
                        "jsonrpc": "2.0",
                        "id": 61,
                        "method": "tools/call",
                        "params": {"name": "device_snapshot", "arguments": {"session_file": session_file}},
                    }
                )
                default_snapshot_2 = server.handle_message(
                    {
                        "jsonrpc": "2.0",
                        "id": 62,
                        "method": "tools/call",
                        "params": {"name": "device_snapshot", "arguments": {"session_file": session_file}},
                    }
                )
                full_snapshot_1 = server.handle_message(
                    {
                        "jsonrpc": "2.0",
                        "id": 63,
                        "method": "tools/call",
                        "params": {
                            "name": "device_snapshot",
                            "arguments": {"session_file": session_file, "interactive": False, "compact": False},
                        },
                    }
                )
                full_snapshot_2 = server.handle_message(
                    {
                        "jsonrpc": "2.0",
                        "id": 64,
                        "method": "tools/call",
                        "params": {
                            "name": "device_snapshot",
                            "arguments": {"session_file": session_file, "interactive": False, "compact": False},
                        },
                    }
                )

            self.assertEqual(
                driver.snapshot_calls,
                [
                    {"interactive_only": True, "compact": True},
                    {"interactive_only": False, "compact": False},
                ],
            )
            self.assertFalse(default_snapshot_1["result"]["structuredContent"]["cache_hit"])  # type: ignore[index]
            self.assertTrue(default_snapshot_2["result"]["structuredContent"]["cache_hit"])  # type: ignore[index]
            self.assertFalse(full_snapshot_1["result"]["structuredContent"]["cache_hit"])  # type: ignore[index]
            self.assertTrue(full_snapshot_2["result"]["structuredContent"]["cache_hit"])  # type: ignore[index]
            self.assertNotEqual(
                default_snapshot_1["result"]["structuredContent"]["result_json"]["tree_hash"],  # type: ignore[index]
                full_snapshot_1["result"]["structuredContent"]["result_json"]["tree_hash"],  # type: ignore[index]
            )

    def test_device_page_map_and_dictionary_are_available(self) -> None:
        with tempfile.TemporaryDirectory(prefix="mcp-device-map-") as tmp:
            session_file = str(Path(tmp) / "session.json")
            server = mcp_server.MCPServer(runner=_FailRunner())
            driver = _SemanticRecordingDriver(
                app={"android_package": "com.example.app"},
                dispatch_commands=False,
            )
            with mock.patch(
                "tools.mcp_server._build_device_driver",
                return_value=driver,
            ):
                open_response = server.handle_message(
                    {
                        "jsonrpc": "2.0",
                        "id": 80,
                        "method": "tools/call",
                        "params": {
                            "name": "device_open",
                            "arguments": {
                                "platform": "android",
                                "app": "com.example.app",
                                "dispatch_commands": False,
                                "session_file": session_file,
                            },
                        },
                    }
                )
                self.assertIsNotNone(open_response)
                open_result = open_response["result"]["structuredContent"]["result_json"]  # type: ignore[index]
                self.assertEqual(open_result["settlement"]["status"], "settled")
                mcp_server.DEVICE_SESSION_CACHE[session_file].snapshot_cache.clear()
                driver.snapshot_calls.clear()

                page_map_response = server.handle_message(
                    {
                        "jsonrpc": "2.0",
                        "id": 81,
                        "method": "tools/call",
                        "params": {"name": "device_page_map", "arguments": {"session_file": session_file}},
                    }
                )
                self.assertIsNotNone(page_map_response)
                page_map = page_map_response["result"]["structuredContent"]["result_json"]  # type: ignore[index]
                page_map_text = page_map_response["result"]["content"][0]["text"]  # type: ignore[index]
                self.assertEqual(page_map["page"]["screen_id"], "home_screen")
                self.assertEqual(page_map["page"]["root"]["id"], "screen.home_screen")
                self.assertEqual(page_map["page"]["root"]["screen_id"], "home_screen")
                self.assertEqual(page_map["page"]["root_resolution"]["strategy"], "snapshot_root")
                self.assertTrue(page_map["page"]["interactive_refs"])
                self.assertTrue(page_map["snapshot"]["live_semantics_ready"])
                self.assertFalse(page_map["snapshot"]["degraded"])
                self.assertFalse(page_map["snapshot"]["consistency"]["ordered_root_matches_snapshot_root"])
                self.assertTrue(any(str(section["id"]).startswith("search_box_") for section in page_map["page"]["sections"]))
                self.assertIn("screen_id=home_screen", page_map_text)
                self.assertIn("capture_source=android_accessibility_bridge", page_map_text)
                self.assertIn("semantic_ids=1", page_map_text)

                dictionary_response = server.handle_message(
                    {
                        "jsonrpc": "2.0",
                        "id": 82,
                        "method": "tools/call",
                        "params": {"name": "device_element_dictionary", "arguments": {"session_file": session_file}},
                    }
                )
                self.assertIsNotNone(dictionary_response)
                dictionary = dictionary_response["result"]["structuredContent"]["result_json"]  # type: ignore[index]
                dictionary_text = dictionary_response["result"]["content"][0]["text"]  # type: ignore[index]
                self.assertIn("search.query_input", dictionary["dictionary"]["semantic_id"])
                self.assertEqual(dictionary["dictionary"]["semantic_id"]["search.query_input"]["count"], 1)
                self.assertIn("home_screen", dictionary["dictionary"]["screen_id"])
                self.assertEqual(dictionary["summary"]["ambiguous_entry_count"], 0)
                self.assertEqual(dictionary["summary"]["field_stats"]["semantic_id"]["value_count"], 1)
                self.assertEqual(dictionary["summary"]["recommended_lookup_fields"], ["semantic_id", "id", "resource_id", "label"])
                self.assertIn("ambiguous_entries=0", dictionary_text)
                self.assertEqual(driver.snapshot_calls, [{"interactive_only": False, "compact": False}])

    def test_device_page_map_reports_degraded_snapshot_state(self) -> None:
        with tempfile.TemporaryDirectory(prefix="mcp-device-map-fallback-") as tmp:
            session_file = str(Path(tmp) / "session.json")
            server = mcp_server.MCPServer(runner=_FailRunner())
            driver = _FallbackRecordingDriver(
                app={"android_package": "com.example.app"},
                dispatch_commands=False,
            )
            with mock.patch("tools.mcp_server._build_device_driver", return_value=driver):
                open_response = server.handle_message(
                    {
                        "jsonrpc": "2.0",
                        "id": 83,
                        "method": "tools/call",
                        "params": {
                            "name": "device_open",
                            "arguments": {
                                "platform": "android",
                                "app": "com.example.app",
                                "dispatch_commands": False,
                                "session_file": session_file,
                            },
                        },
                    }
                )
                self.assertIsNotNone(open_response)
                mcp_server.DEVICE_SESSION_CACHE[session_file].snapshot_cache.clear()
                driver.snapshot_calls.clear()

                page_map_response = server.handle_message(
                    {
                        "jsonrpc": "2.0",
                        "id": 84,
                        "method": "tools/call",
                        "params": {"name": "device_page_map", "arguments": {"session_file": session_file}},
                    }
                )
                dictionary_response = server.handle_message(
                    {
                        "jsonrpc": "2.0",
                        "id": 85,
                        "method": "tools/call",
                        "params": {"name": "device_element_dictionary", "arguments": {"session_file": session_file}},
                    }
                )

            self.assertIsNotNone(page_map_response)
            page_map = page_map_response["result"]["structuredContent"]["result_json"]  # type: ignore[index]
            page_map_text = page_map_response["result"]["content"][0]["text"]  # type: ignore[index]
            self.assertEqual(page_map["snapshot"]["capture_source"], "adb_uiautomator_fallback")
            self.assertEqual(page_map["snapshot"]["semantic_id_count"], 0)
            self.assertFalse(page_map["snapshot"]["live_semantics_ready"])
            self.assertTrue(page_map["snapshot"]["degraded"])
            self.assertIn("capture_source_degraded", page_map["snapshot"]["degraded_reasons"])
            self.assertIn("missing_semantic_ids", page_map["snapshot"]["degraded_reasons"])
            self.assertIn("degraded=true", page_map_text)

            self.assertIsNotNone(dictionary_response)
            dictionary = dictionary_response["result"]["structuredContent"]["result_json"]  # type: ignore[index]
            self.assertEqual(dictionary["summary"]["field_stats"]["screen_id"]["value_count"], 0)
            self.assertEqual(dictionary["summary"]["field_stats"]["semantic_id"]["value_count"], 0)
            self.assertEqual(
                dictionary["summary"]["recommended_lookup_fields"],
                ["screen_id", "id", "resource_id", "label", "text", "content_desc"],
            )

    def test_device_press_selector_can_fail_closed_on_ambiguity(self) -> None:
        with tempfile.TemporaryDirectory(prefix="mcp-device-ambiguous-") as tmp:
            session_file = str(Path(tmp) / "session.json")
            server = mcp_server.MCPServer(runner=_FailRunner())

            with mock.patch("tools.mcp_server._build_device_driver", return_value=_AmbiguousSelectorDriver(app={"android_package": "com.example.app"}, dispatch_commands=False)):
                open_response = server.handle_message(
                    {
                        "jsonrpc": "2.0",
                        "id": 90,
                        "method": "tools/call",
                        "params": {
                            "name": "device_open",
                            "arguments": {
                                "platform": "android",
                                "app": "com.example.app",
                                "dispatch_commands": False,
                                "session_file": session_file,
                            },
                        },
                    }
                )
                self.assertIsNotNone(open_response)

                press_response = server.handle_message(
                    {
                        "jsonrpc": "2.0",
                        "id": 91,
                        "method": "tools/call",
                        "params": {
                            "name": "device_press",
                            "arguments": {
                                "session_file": session_file,
                                "selector": {"by": "id", "value": "save"},
                            },
                        },
                    }
                )

            self.assertIsNotNone(press_response)
            self.assertTrue(press_response["result"]["isError"])  # type: ignore[index]
            result = press_response["result"]["structuredContent"]["result_json"]["result"]  # type: ignore[index]
            self.assertEqual(result["error_code"], "ambiguous_selector")
            self.assertEqual(result["selector_info"]["match_type"], "ambiguous")
            self.assertEqual(len(result["candidates"]), 2)

    def test_tools_call_text_content_is_smaller_than_structured_payload(self) -> None:
        with tempfile.TemporaryDirectory(prefix="mcp-device-text-") as tmp:
            session_file = str(Path(tmp) / "session.json")
            driver = _RecordingDriver(app={"android_package": "com.example.app"}, dispatch_commands=False)
            server = mcp_server.MCPServer(runner=_FailRunner())

            with mock.patch("tools.mcp_server._build_device_driver", return_value=driver):
                open_response = server.handle_message(
                    {
                        "jsonrpc": "2.0",
                        "id": 70,
                        "method": "tools/call",
                        "params": {
                            "name": "device_open",
                            "arguments": {
                                "platform": "android",
                                "app": "com.example.app",
                                "dispatch_commands": False,
                                "session_file": session_file,
                            },
                        },
                    }
                )
                self.assertIsNotNone(open_response)

                snapshot_response = server.handle_message(
                    {
                        "jsonrpc": "2.0",
                        "id": 71,
                        "method": "tools/call",
                        "params": {"name": "device_snapshot", "arguments": {"session_file": session_file}},
                    }
                )

            self.assertIsNotNone(snapshot_response)
            result = snapshot_response["result"]  # type: ignore[index]
            structured = result["structuredContent"]
            text_payload = result["content"][0]["text"]
            structured_json = json.dumps(structured, ensure_ascii=True)

            self.assertIn("snapshot_options=1:1", text_payload)
            self.assertNotIn('"result_json"', text_payload)
            self.assertLess(len(text_payload), len(structured_json) // 2)

    def test_device_verify_mismatch_is_reported_as_error(self) -> None:
        with tempfile.TemporaryDirectory(prefix="mcp-device-verify-mismatch-") as tmp:
            session_file = str(Path(tmp) / "session.json")
            server = mcp_server.MCPServer(runner=_FailRunner())
            open_response = server.handle_message(
                {
                    "jsonrpc": "2.0",
                    "id": 40,
                    "method": "tools/call",
                    "params": {
                        "name": "device_open",
                        "arguments": {
                            "platform": "android",
                            "app": "com.example.app",
                            "dispatch_commands": False,
                            "session_file": session_file,
                        },
                    },
                }
            )
            self.assertIsNotNone(open_response)
            self.assertFalse(open_response["result"]["isError"])  # type: ignore[index]

            snapshot_response = server.handle_message(
                {
                    "jsonrpc": "2.0",
                    "id": 41,
                    "method": "tools/call",
                    "params": {"name": "device_snapshot", "arguments": {"session_file": session_file}},
                }
            )
            self.assertIsNotNone(snapshot_response)
            self.assertFalse(snapshot_response["result"]["isError"])  # type: ignore[index]

            verify_response = server.handle_message(
                {
                    "jsonrpc": "2.0",
                    "id": 42,
                    "method": "tools/call",
                    "params": {
                        "name": "device_verify",
                        "arguments": {
                            "session_file": session_file,
                            "element": "search_box",
                            "expected": "mismatch-value",
                            "timeout_ms": 100,
                        },
                    },
                }
            )
            self.assertIsNotNone(verify_response)
            self.assertTrue(verify_response["result"]["isError"])  # type: ignore[index]
            verify_result = verify_response["result"]["structuredContent"]["result_json"]["result"]  # type: ignore[index]
            self.assertEqual(verify_result["verdict"], "fail")
            self.assertEqual(verify_result["error_code"], "assertion_mismatch")

    def test_device_fill_retries_with_full_semantic_snapshot_after_selector_drift(self) -> None:
        with tempfile.TemporaryDirectory(prefix="mcp-device-fill-retry-") as tmp:
            session_file = str(Path(tmp) / "session.json")
            server = mcp_server.MCPServer(runner=_FailRunner())
            driver = _SelectorDriftRetryDriver(app={"android_package": "com.example.app"}, dispatch_commands=False)

            with mock.patch("tools.mcp_server._build_device_driver", return_value=driver):
                open_response = server.handle_message(
                    {
                        "jsonrpc": "2.0",
                        "id": 120,
                        "method": "tools/call",
                        "params": {
                            "name": "device_open",
                            "arguments": {
                                "platform": "android",
                                "app": "com.example.app",
                                "dispatch_commands": False,
                                "session_file": session_file,
                            },
                        },
                    }
                )
                self.assertIsNotNone(open_response)
                mcp_server.DEVICE_SESSION_CACHE[session_file].snapshot_cache.clear()
                driver.raw_snapshot_calls.clear()

                fill_response = server.handle_message(
                    {
                        "jsonrpc": "2.0",
                        "id": 121,
                        "method": "tools/call",
                        "params": {
                            "name": "device_fill",
                            "arguments": {
                                "session_file": session_file,
                                "element": "search.query_input",
                                "text": "hello",
                            },
                        },
                    }
                )

            self.assertIsNotNone(fill_response)
            self.assertFalse(fill_response["result"]["isError"])  # type: ignore[index]
            result_json = fill_response["result"]["structuredContent"]["result_json"]  # type: ignore[index]
            result = result_json["result"]
            self.assertEqual(result_json["status"], "ok")
            self.assertEqual(result["status"], "ok")
            self.assertEqual(result["selector"], "search.query_input")
            self.assertTrue(result["retry_context"]["attempted_full_snapshot"])
            self.assertTrue(result["retry_context"]["semantic_retry_preserved"])
            self.assertTrue(result["retry_context"]["full_snapshot"]["live_semantics_ready"])
            self.assertEqual(result_json["settlement"]["status"], "settled")
            self.assertEqual(
                driver.raw_snapshot_calls[0],
                {"interactive_only": False, "compact": False, "bridge_first_full": True},
            )
            self.assertEqual(
                driver.raw_snapshot_calls[1:],
                [
                    {"interactive_only": False, "compact": False},
                    {"interactive_only": False, "compact": False},
                ],
            )

    def test_device_fill_reports_degraded_retry_when_full_snapshot_falls_back(self) -> None:
        with tempfile.TemporaryDirectory(prefix="mcp-device-fill-fallback-retry-") as tmp:
            session_file = str(Path(tmp) / "session.json")
            server = mcp_server.MCPServer(runner=_FailRunner())
            driver = _SelectorDriftFallbackDriver(app={"android_package": "com.example.app"}, dispatch_commands=False)

            with mock.patch("tools.mcp_server._build_device_driver", return_value=driver):
                open_response = server.handle_message(
                    {
                        "jsonrpc": "2.0",
                        "id": 122,
                        "method": "tools/call",
                        "params": {
                            "name": "device_open",
                            "arguments": {
                                "platform": "android",
                                "app": "com.example.app",
                                "dispatch_commands": False,
                                "session_file": session_file,
                            },
                        },
                    }
                )
                self.assertIsNotNone(open_response)
                mcp_server.DEVICE_SESSION_CACHE[session_file].snapshot_cache.clear()

                fill_response = server.handle_message(
                    {
                        "jsonrpc": "2.0",
                        "id": 123,
                        "method": "tools/call",
                        "params": {
                            "name": "device_fill",
                            "arguments": {
                                "session_file": session_file,
                                "element": "search.query_input",
                                "text": "hello",
                            },
                        },
                    }
                )

            self.assertIsNotNone(fill_response)
            self.assertTrue(fill_response["result"]["isError"])  # type: ignore[index]
            result_json = fill_response["result"]["structuredContent"]["result_json"]  # type: ignore[index]
            result = result_json["result"]
            self.assertEqual(result_json["status"], "error")
            self.assertEqual(result["error_code"], "selector_retry_degraded")
            self.assertTrue(result["degraded"])
            self.assertTrue(result["retry_context"]["full_snapshot"]["degraded"])
            self.assertFalse(result["retry_context"]["semantic_retry_preserved"])
            self.assertIsNone(result_json["settlement"])

    def test_device_press_and_fill_post_action_settlement_stays_semantic(self) -> None:
        self._assert_post_action_settlement_stays_semantic(
            tool_name="device_press",
            arguments={"element": "search.query_input"},
        )
        self._assert_post_action_settlement_stays_semantic(
            tool_name="device_fill",
            arguments={"element": "search.query_input", "text": "hello"},
        )

    def test_device_open_reports_settlement_timeout(self) -> None:
        with tempfile.TemporaryDirectory(prefix="mcp-device-open-timeout-") as tmp:
            session_file = str(Path(tmp) / "session.json")
            server = mcp_server.MCPServer(runner=_FailRunner())
            driver = _NeverSettlesDriver(app={"android_package": "com.example.app"}, dispatch_commands=False)

            with mock.patch("tools.mcp_server._build_device_driver", return_value=driver):
                open_response = server.handle_message(
                    {
                        "jsonrpc": "2.0",
                        "id": 124,
                        "method": "tools/call",
                        "params": {
                            "name": "device_open",
                            "arguments": {
                                "platform": "android",
                                "app": "com.example.app",
                                "dispatch_commands": False,
                                "session_file": session_file,
                            },
                        },
                    }
                )

            self.assertIsNotNone(open_response)
            self.assertTrue(open_response["result"]["isError"])  # type: ignore[index]
            result_json = open_response["result"]["structuredContent"]["result_json"]  # type: ignore[index]
            self.assertEqual(result_json["status"], "error")
            self.assertEqual(result_json["settlement"]["status"], "timeout")

    def test_device_open_prefers_semantic_snapshot_for_warm_launch_recovery(self) -> None:
        with tempfile.TemporaryDirectory(prefix="mcp-device-open-warm-launch-") as tmp:
            session_file = str(Path(tmp) / "session.json")
            server = mcp_server.MCPServer(runner=_FailRunner())
            driver = _WarmLaunchSemanticRecoveryDriver(
                app={"android_package": "com.example.app"},
                dispatch_commands=False,
            )

            with mock.patch("tools.mcp_server._build_device_driver", return_value=driver):
                open_response = server.handle_message(
                    {
                        "jsonrpc": "2.0",
                        "id": 125,
                        "method": "tools/call",
                        "params": {
                            "name": "device_open",
                            "arguments": {
                                "platform": "android",
                                "app": "com.example.app",
                                "dispatch_commands": False,
                                "session_file": session_file,
                            },
                        },
                    }
                )
                page_map_response = server.handle_message(
                    {
                        "jsonrpc": "2.0",
                        "id": 126,
                        "method": "tools/call",
                        "params": {"name": "device_page_map", "arguments": {"session_file": session_file}},
                    }
                )

            self.assertIsNotNone(open_response)
            self.assertFalse(open_response["result"]["isError"])  # type: ignore[index]
            open_result = open_response["result"]["structuredContent"]["result_json"]  # type: ignore[index]
            self.assertEqual(open_result["settlement"]["status"], "settled")
            self.assertEqual(open_result["settlement"]["screen_id"], "screen.settings")
            self.assertTrue(open_result["settlement"]["snapshot"]["live_semantics_ready"])
            self.assertFalse(open_result["settlement"]["degraded"])
            self.assertEqual(
                driver.raw_snapshot_calls,
                [
                    {"interactive_only": False, "compact": False, "bridge_first_full": True},
                    {"interactive_only": False, "compact": False, "bridge_first_full": True},
                    {"interactive_only": False, "compact": False, "bridge_first_full": True},
                ],
            )

            self.assertIsNotNone(page_map_response)
            page_map_result = page_map_response["result"]["structuredContent"]  # type: ignore[index]
            page_map = page_map_result["result_json"]
            self.assertTrue(page_map_result["cache_hit"])
            self.assertEqual(page_map["page"]["screen_id"], "screen.settings")
            self.assertEqual(page_map["page"]["root"]["id"], "screen.settings")
            self.assertTrue(page_map["snapshot"]["live_semantics_ready"])
            self.assertFalse(page_map["snapshot"]["degraded"])


if __name__ == "__main__":
    unittest.main()
