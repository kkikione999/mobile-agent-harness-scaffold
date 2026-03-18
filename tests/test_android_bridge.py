from __future__ import annotations

import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from harness.driver.android_bridge import AndroidBridgeConfig, AndroidTreeClient


class _BridgeHandler(BaseHTTPRequestHandler):
    health_payload: dict[str, object] = {"ready": True, "package": "com.example.app", "protocol_version": "bridge.v1"}
    snapshot_payload: dict[str, object] = {
        "root": "n0",
        "nodes": [
            {
                "node_id": "n0",
                "parent_id": None,
                "class_name": "android.widget.FrameLayout",
                "resource_id": "root",
                "text": "",
                "content_desc": "Root",
                "bounds": [0, 0, 1080, 2400],
                "clickable": False,
            }
        ],
    }

    def log_message(self, format: str, *args: object) -> None:  # noqa: A003
        _ = (format, args)

    def _write_json(self, status: int, payload: dict[str, object]) -> None:
        body = json.dumps(payload, ensure_ascii=True).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        if self.path.startswith("/health"):
            self._write_json(200, self.health_payload)
            return
        self._write_json(404, {"error": "not_found"})

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/tree/snapshot":
            self._write_json(404, {"error": "not_found"})
            return
        content_length = int(self.headers.get("Content-Length", "0"))
        _ = self.rfile.read(content_length)
        self._write_json(200, self.snapshot_payload)


class TestAndroidBridge(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), _BridgeHandler)
        cls.server_thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.server_thread.start()
        cls.port = cls.server.server_address[1]

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()
        cls.server_thread.join(timeout=2)

    def _client(
        self,
        *,
        forward_result: dict[str, object] | None = None,
        forward_list_result: dict[str, object] | None = None,
    ) -> tuple[AndroidTreeClient, list[list[str]]]:
        client = AndroidTreeClient(AndroidBridgeConfig(local_port=self.port, remote_port=self.port, timeout_seconds=1.0))
        client.ensure_port_forward = lambda: forward_result or {  # type: ignore[method-assign]
            "status": "ok",
            "command": "adb forward tcp:test tcp:test",
            "returncode": 0,
            "stdout": "",
            "stderr": "",
            "latency_ms": 0,
        }
        adb_calls: list[list[str]] = []

        def run_adb(args: list[str]) -> dict[str, object]:
            adb_calls.append(list(args))
            return forward_list_result or {
                "command": "adb forward --list",
                "returncode": 0,
                "stdout": "",
                "stderr": "",
                "latency_ms": 0,
            }

        client._run_adb = run_adb  # type: ignore[method-assign]
        return client, adb_calls

    def test_health_success(self) -> None:
        _BridgeHandler.health_payload = {"ready": True, "package": "com.example.app", "protocol_version": "bridge.v1"}
        client, adb_calls = self._client()
        result = client.health(app_package="com.example.app")
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["bridge_status"], "ok")
        self.assertEqual(adb_calls, [])
        self.assertNotIn("adb_forward_list", result["capture_trace"])

    def test_health_status_ok_without_ready(self) -> None:
        _BridgeHandler.health_payload = {"status": "ok", "package": "com.example.app"}
        client, adb_calls = self._client()
        result = client.health(app_package="com.example.app")
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["bridge_status"], "ok")
        self.assertEqual(adb_calls, [])

    def test_health_failure_collects_forward_list_diagnostics(self) -> None:
        _BridgeHandler.health_payload = {"ready": False, "package": "com.example.app"}
        client, adb_calls = self._client(
            forward_list_result={
                "status": "ok",
                "command": "adb forward --list",
                "returncode": 0,
                "stdout": "emulator-5554 tcp:18765 tcp:18765",
                "stderr": "",
                "latency_ms": 0,
                "entries": [
                    {
                        "serial": "emulator-5554",
                        "local": "tcp:18765",
                        "remote": "tcp:18765",
                        "local_port": 18765,
                        "remote_port": 18765,
                        "matches_config": True,
                    }
                ],
                "forward_active": True,
                "bridge_config": {
                    "local_port": self.port,
                    "remote_port": self.port,
                    "timeout_seconds": 1.0,
                    "serial": None,
                },
            }
        )
        client.collect_runtime_diagnostics = lambda app_package: {  # type: ignore[method-assign]
            "status": "ok",
            "app_process": {
                "package": app_package,
                "pid": "15418",
                "running": True,
                "pidof": {"returncode": 0, "stdout": "15418", "stderr": "", "latency_ms": 1},
            },
            "bridge_port": {
                "port": self.port,
                "listening": True,
                "owned_by_app": True,
                "listeners": [{"local_port": self.port, "pid": "15418"}],
            },
            "ss": {"returncode": 0, "stdout": "", "stderr": "", "latency_ms": 1},
        }
        result = client.health(app_package="com.example.app")
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["error_code"], "bridge_not_integrated")
        self.assertEqual(result["bridge_error_code"], "bridge_not_integrated")
        self.assertEqual(adb_calls, [["forward", "--list"]])
        self.assertTrue(result["capture_trace"]["adb_forward_list"]["forward_active"])

    def test_health_http_error_classifies_app_not_running(self) -> None:
        client, adb_calls = self._client(
            forward_list_result={
                "status": "ok",
                "command": "adb forward --list",
                "returncode": 0,
                "stdout": "",
                "stderr": "",
                "latency_ms": 0,
                "entries": [],
                "forward_active": False,
                "bridge_config": {
                    "local_port": self.port,
                    "remote_port": self.port,
                    "timeout_seconds": 1.0,
                    "serial": None,
                },
            }
        )
        client._request_json = lambda method, path, payload=None: {  # type: ignore[method-assign]
            "status": "error",
            "error_code": "bridge_http_error",
            "details": "bridge endpoint returned http 502",
            "http_status": 502,
            "latency_ms": 4,
        }
        client.collect_runtime_diagnostics = lambda app_package: {  # type: ignore[method-assign]
            "status": "ok",
            "app_process": {
                "package": app_package,
                "pid": None,
                "running": False,
                "pidof": {"returncode": 1, "stdout": "", "stderr": "", "latency_ms": 1},
            },
            "bridge_port": {"port": self.port, "listening": False, "owned_by_app": False, "listeners": []},
            "ss": {"returncode": 0, "stdout": "", "stderr": "", "latency_ms": 1},
        }
        result = client.health(app_package="com.example.app")
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["error_code"], "app_not_running")
        self.assertEqual(result["bridge_error_code"], "bridge_http_error")
        self.assertEqual(adb_calls, [["forward", "--list"]])
        self.assertFalse(result["capture_trace"]["runtime"]["app_process"]["running"])

    def test_health_http_error_classifies_bridge_port_not_listening(self) -> None:
        client, _ = self._client()
        client._request_json = lambda method, path, payload=None: {  # type: ignore[method-assign]
            "status": "error",
            "error_code": "bridge_http_error",
            "details": "bridge endpoint returned http 502",
            "http_status": 502,
            "latency_ms": 4,
        }
        client.collect_runtime_diagnostics = lambda app_package: {  # type: ignore[method-assign]
            "status": "ok",
            "app_process": {
                "package": app_package,
                "pid": "15418",
                "running": True,
                "pidof": {"returncode": 0, "stdout": "15418", "stderr": "", "latency_ms": 1},
            },
            "bridge_port": {"port": self.port, "listening": False, "owned_by_app": False, "listeners": []},
            "ss": {"returncode": 0, "stdout": "", "stderr": "", "latency_ms": 1},
        }
        result = client.health(app_package="com.example.app")
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["error_code"], "bridge_port_not_listening")
        self.assertEqual(result["bridge_error_code"], "bridge_http_error")
        self.assertIn(str(self.port), result["details"])

    def test_snapshot_protocol_invalid_nodes(self) -> None:
        _BridgeHandler.snapshot_payload = {"root": "n0", "nodes": "invalid"}  # type: ignore[assignment]
        client, _ = self._client()
        result = client.snapshot(app_package="com.example.app", options={"compact": True})
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["error_code"], "bridge_protocol_invalid")

    def test_snapshot_http_error_includes_runtime_classification(self) -> None:
        client, _ = self._client()
        client._request_json = lambda method, path, payload=None: {  # type: ignore[method-assign]
            "status": "error",
            "error_code": "bridge_http_error",
            "details": "bridge endpoint returned http 502",
            "http_status": 502,
            "latency_ms": 7,
        }
        client.collect_runtime_diagnostics = lambda app_package: {  # type: ignore[method-assign]
            "status": "ok",
            "app_process": {
                "package": app_package,
                "pid": "15418",
                "running": True,
                "pidof": {"returncode": 0, "stdout": "15418", "stderr": "", "latency_ms": 1},
            },
            "bridge_port": {
                "port": self.port,
                "listening": True,
                "owned_by_app": True,
                "listeners": [{"local_port": self.port, "pid": "15418"}],
            },
            "ss": {"returncode": 0, "stdout": "", "stderr": "", "latency_ms": 1},
        }
        result = client.snapshot(app_package="com.example.app", options={"compact": True})
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["error_code"], "bridge_http_error")
        self.assertEqual(result["bridge_error_code"], "bridge_http_error")
        self.assertTrue(result["capture_trace"]["runtime"]["bridge_port"]["owned_by_app"])

    def test_collect_runtime_diagnostics_parses_pid_and_listener_rows(self) -> None:
        client = AndroidTreeClient(
            AndroidBridgeConfig(local_port=18765, remote_port=18765, timeout_seconds=1.0, serial="emulator-5554")
        )
        calls: list[list[str]] = []

        def run_adb(args: list[str]) -> dict[str, object]:
            calls.append(list(args))
            if args[:2] == ["shell", "pidof"]:
                return {
                    "command": "adb shell pidof com.example.app",
                    "returncode": 0,
                    "stdout": "15418",
                    "stderr": "",
                    "latency_ms": 1,
                }
            return {
                "command": "adb shell ss -lntp",
                "returncode": 0,
                "stdout": (
                    "State Recv-Q Send-Q Local Address:Port Peer Address:Port\n"
                    "LISTEN 0 50 *:18765 *:* users:((\"com.example.app\",pid=15418,fd=109))\n"
                    "LISTEN 0 4 *:5555 *:* users:((\"adbd\",pid=2361,fd=12))"
                ),
                "stderr": "",
                "latency_ms": 1,
            }

        client._run_adb = run_adb  # type: ignore[method-assign]
        result = client.collect_runtime_diagnostics("com.example.app")
        self.assertEqual(calls, [["shell", "pidof", "com.example.app"], ["shell", "ss", "-lntp"]])
        self.assertTrue(result["app_process"]["running"])
        self.assertTrue(result["bridge_port"]["listening"])
        self.assertTrue(result["bridge_port"]["owned_by_app"])
        self.assertEqual(result["bridge_port"]["listeners"][0]["process"], "com.example.app")

    def test_list_port_forwards_parses_entries(self) -> None:
        client = AndroidTreeClient(
            AndroidBridgeConfig(local_port=18765, remote_port=18765, timeout_seconds=1.0, serial="emulator-5554")
        )
        client._run_adb = lambda args: {  # type: ignore[method-assign]
            "command": "adb forward --list",
            "returncode": 0,
            "stdout": "emulator-5554 tcp:18765 tcp:18765\nother tcp:1111 tcp:2222",
            "stderr": "",
            "latency_ms": 1,
        }
        result = client.list_port_forwards()
        self.assertEqual(result["status"], "ok")
        self.assertTrue(result["forward_active"])
        entries = result["entries"]
        self.assertEqual(entries[0]["local_port"], 18765)
        self.assertTrue(entries[0]["matches_config"])


if __name__ == "__main__":
    unittest.main()
