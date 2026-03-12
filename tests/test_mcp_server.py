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
        self.state: dict[str, Any] = {}

    def preflight(self) -> dict[str, Any]:
        return {"status": "ok"}

    def interact(self, action: dict[str, Any], elements: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        _ = elements
        if action.get("action") == "launch_app":
            return {"status": "ok"}
        return {"status": "ok", "action": action.get("action")}

    def snapshot(self, options: dict[str, Any] | None = None) -> dict[str, Any]:
        resolved = {
            "interactive_only": bool((options or {}).get("interactive_only", False)),
            "compact": bool((options or {}).get("compact", False)),
        }
        self.snapshot_calls.append(resolved)
        suffix = f"{int(resolved['interactive_only'])}:{int(resolved['compact'])}:{len(self.snapshot_calls)}"
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
                "interactive": resolved["interactive_only"],
                "enabled": True,
                "visible": True,
                "bounds": [0, 0, 100, 40],
                "path": "0/0",
            }
        ]
        return {
            "schema_version": "cat.v2",
            "tree_hash": suffix,
            "screen_id": "home_screen",
            "elements": elements,
            "options": resolved,
            "element_map": {element["id"]: element["ref"] for element in elements},
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
        payload["screen_id"] = "home_screen"
        payload["elements"][0]["screen_id"] = "home_screen"
        payload["elements"][1]["screen_id"] = "home_screen"
        payload["elements"][1]["semantic_id"] = "search.query_input"
        return payload


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
            with mock.patch(
                "tools.mcp_server._build_device_driver",
                return_value=_SemanticRecordingDriver(
                    app={"android_package": "com.example.app"},
                    dispatch_commands=False,
                ),
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
                self.assertEqual(page_map["page"]["screen_id"], "home_screen")
                self.assertEqual(page_map["page"]["root"]["id"], "screen.home_screen")
                self.assertEqual(page_map["page"]["root"]["screen_id"], "home_screen")
                self.assertTrue(page_map["page"]["interactive_refs"])
                self.assertTrue(any(str(section["id"]).startswith("search_box_") for section in page_map["page"]["sections"]))

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
                self.assertIn("search.query_input", dictionary["dictionary"]["semantic_id"])
                self.assertEqual(dictionary["dictionary"]["semantic_id"]["search.query_input"]["count"], 1)
                self.assertIn("home_screen", dictionary["dictionary"]["screen_id"])

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


if __name__ == "__main__":
    unittest.main()
