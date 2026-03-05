from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import Any

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


if __name__ == "__main__":
    unittest.main()
