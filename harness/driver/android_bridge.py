from __future__ import annotations

import json
import subprocess
import time
import uuid
from dataclasses import dataclass
from typing import Any
from urllib import error, request


@dataclass(frozen=True)
class AndroidBridgeConfig:
    local_port: int = 18765
    remote_port: int = 18765
    timeout_seconds: float = 3.0
    serial: str | None = None


class AndroidTreeClient:
    def __init__(self, config: AndroidBridgeConfig) -> None:
        self.config = config

    def _config_payload(self) -> dict[str, Any]:
        return {
            "local_port": self.config.local_port,
            "remote_port": self.config.remote_port,
            "timeout_seconds": self.config.timeout_seconds,
            "serial": self.config.serial,
        }

    def _adb_prefix(self) -> list[str]:
        prefix = ["adb"]
        if self.config.serial:
            prefix.extend(["-s", self.config.serial])
        return prefix

    def _run_adb(self, args: list[str]) -> dict[str, Any]:
        cmd = self._adb_prefix() + args
        started = time.perf_counter()
        try:
            completed = subprocess.run(cmd, capture_output=True, text=True, check=False)
        except FileNotFoundError as exc:
            elapsed_ms = int((time.perf_counter() - started) * 1000)
            return {
                "command": " ".join(cmd),
                "returncode": 127,
                "stdout": "",
                "stderr": str(exc),
                "latency_ms": elapsed_ms,
            }
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        return {
            "command": " ".join(cmd),
            "returncode": completed.returncode,
            "stdout": completed.stdout.strip(),
            "stderr": completed.stderr.strip(),
            "latency_ms": elapsed_ms,
        }

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.config.local_port}"

    def ensure_port_forward(self) -> dict[str, Any]:
        result = self._run_adb(["forward", f"tcp:{self.config.local_port}", f"tcp:{self.config.remote_port}"])
        if result["returncode"] != 0:
            return {
                "status": "error",
                "error_code": "bridge_forward_failed",
                "details": "failed to create adb forward tunnel for Android bridge",
                "bridge_config": self._config_payload(),
                **result,
            }
        return {"status": "ok", "bridge_config": self._config_payload(), **result}

    @staticmethod
    def _parse_forward_port(value: str) -> int | None:
        if ":" not in value:
            return None
        tail = value.split(":", 1)[1]
        try:
            return int(tail)
        except ValueError:
            return None

    def list_port_forwards(self) -> dict[str, Any]:
        result = self._run_adb(["forward", "--list"])
        if result["returncode"] != 0:
            return {
                "status": "error",
                "error_code": "bridge_forward_list_failed",
                "details": "failed to list adb forward rules",
                "bridge_config": self._config_payload(),
                **result,
            }

        entries: list[dict[str, Any]] = []
        for line in result.get("stdout", "").splitlines():
            parts = line.split()
            if len(parts) < 3:
                continue
            serial, local, remote = parts[:3]
            entry: dict[str, Any] = {
                "serial": serial,
                "local": local,
                "remote": remote,
            }
            local_port = self._parse_forward_port(local)
            remote_port = self._parse_forward_port(remote)
            if local_port is not None:
                entry["local_port"] = local_port
            if remote_port is not None:
                entry["remote_port"] = remote_port

            matches = local_port == self.config.local_port and remote_port == self.config.remote_port
            if self.config.serial:
                matches = matches and serial == self.config.serial
            entry["matches_config"] = matches
            entries.append(entry)

        forward_active = any(entry.get("matches_config") for entry in entries)
        return {
            "status": "ok",
            "entries": entries,
            "forward_active": forward_active,
            "bridge_config": self._config_payload(),
            **result,
        }

    def _request_json(self, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        body: bytes | None = None
        headers = {"Accept": "application/json"}
        if payload is not None:
            body = json.dumps(payload, ensure_ascii=True).encode("utf-8")
            headers["Content-Type"] = "application/json"

        url = f"{self.base_url}{path}"
        req = request.Request(url, data=body, method=method, headers=headers)
        started = time.perf_counter()
        try:
            with request.urlopen(req, timeout=self.config.timeout_seconds) as resp:
                raw = resp.read().decode("utf-8")
                parsed = json.loads(raw) if raw else {}
                elapsed_ms = int((time.perf_counter() - started) * 1000)
                return {
                    "status": "ok",
                    "url": url,
                    "http_status": resp.status,
                    "body": parsed,
                    "raw_body": raw,
                    "latency_ms": elapsed_ms,
                }
        except error.HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            elapsed_ms = int((time.perf_counter() - started) * 1000)
            return {
                "status": "error",
                "error_code": "bridge_http_error",
                "details": f"bridge endpoint returned http {exc.code}",
                "url": url,
                "http_status": exc.code,
                "raw_body": raw,
                "latency_ms": elapsed_ms,
            }
        except error.URLError as exc:
            elapsed_ms = int((time.perf_counter() - started) * 1000)
            return {
                "status": "error",
                "error_code": "bridge_unreachable",
                "details": str(exc.reason),
                "url": url,
                "latency_ms": elapsed_ms,
            }
        except TimeoutError:
            elapsed_ms = int((time.perf_counter() - started) * 1000)
            return {
                "status": "error",
                "error_code": "bridge_timeout",
                "details": "bridge request timed out",
                "url": url,
                "latency_ms": elapsed_ms,
            }
        except json.JSONDecodeError as exc:
            elapsed_ms = int((time.perf_counter() - started) * 1000)
            return {
                "status": "error",
                "error_code": "bridge_protocol_invalid",
                "details": f"bridge returned invalid json: {exc}",
                "url": url,
                "latency_ms": elapsed_ms,
            }

    def health(self, app_package: str) -> dict[str, Any]:
        request_id = str(uuid.uuid4())
        adb_result = self.ensure_port_forward()
        trace: dict[str, Any] = {
            "capture_source": "android_accessibility_bridge",
            "request_id": request_id,
            "adb_forward": adb_result,
            "bridge_config": self._config_payload(),
        }
        if adb_result["status"] != "ok":
            trace["adb_forward_list"] = self.list_port_forwards()
            return {
                "status": "error",
                "error_code": adb_result["error_code"],
                "details": adb_result.get("details"),
                "bridge_status": "forward_failed",
                "bridge_error_code": adb_result["error_code"],
                "bridge_http_status": None,
                "capture_trace": trace,
            }

        response = self._request_json("GET", f"/health?package={app_package}")
        trace["http"] = response
        if response["status"] != "ok":
            trace["adb_forward_list"] = self.list_port_forwards()
            return {
                "status": "error",
                "error_code": response["error_code"],
                "details": response.get("details", "bridge health request failed"),
                "bridge_status": "error",
                "bridge_error_code": response["error_code"],
                "bridge_http_status": response.get("http_status"),
                "capture_trace": trace,
            }

        body = response.get("body")
        if not isinstance(body, dict):
            trace["adb_forward_list"] = self.list_port_forwards()
            return {
                "status": "error",
                "error_code": "bridge_protocol_invalid",
                "details": "bridge health payload was not an object",
                "bridge_status": "error",
                "bridge_error_code": "bridge_protocol_invalid",
                "bridge_http_status": response.get("http_status"),
                "capture_trace": trace,
            }

        ready_value = body.get("ready")
        if ready_value is None:
            status_value = str(body.get("status", "")).strip().lower()
            ready = status_value in {"ok", "ready", "true"}
        else:
            ready = bool(ready_value)
        bridge_package = str(body.get("package", ""))
        if not ready or (bridge_package and bridge_package != app_package):
            trace["adb_forward_list"] = self.list_port_forwards()
            return {
                "status": "error",
                "error_code": "bridge_not_integrated",
                "details": "target app does not expose ready accessibility bridge",
                "bridge_status": "not_ready",
                "bridge_error_code": "bridge_not_integrated",
                "bridge_http_status": response.get("http_status"),
                "capture_trace": trace,
                "health_payload": body,
            }

        return {
            "status": "ok",
            "bridge_status": "ok",
            "bridge_error_code": None,
            "bridge_http_status": response.get("http_status"),
            "capture_trace": trace,
            "health_payload": body,
        }

    def snapshot(self, app_package: str, options: dict[str, Any] | None = None) -> dict[str, Any]:
        request_id = str(uuid.uuid4())
        options = dict(options or {})
        payload = {
            "request_id": request_id,
            "package": app_package,
            "interactive_only": bool(options.get("interactive_only", False)),
            "compact": bool(options.get("compact", True)),
            "include_invisible": bool(options.get("include_invisible", False)),
            "timeout_ms": int(options.get("timeout_ms", 3000)),
        }

        adb_result = self.ensure_port_forward()
        trace: dict[str, Any] = {
            "capture_source": "android_accessibility_bridge",
            "request_id": request_id,
            "request_payload": payload,
            "adb_forward": adb_result,
            "bridge_config": self._config_payload(),
        }
        if adb_result["status"] != "ok":
            return {
                "status": "error",
                "request_id": request_id,
                "error_code": adb_result["error_code"],
                "details": adb_result.get("details"),
                "bridge_status": "forward_failed",
                "bridge_error_code": adb_result["error_code"],
                "bridge_http_status": None,
                "capture_trace": trace,
                "payload": None,
                "latency_ms": adb_result.get("latency_ms", 0),
            }

        response = self._request_json("POST", "/tree/snapshot", payload=payload)
        trace["http"] = response
        if response["status"] != "ok":
            return {
                "status": "error",
                "request_id": request_id,
                "error_code": response["error_code"],
                "details": response.get("details", "bridge snapshot request failed"),
                "bridge_status": "error",
                "bridge_error_code": response["error_code"],
                "bridge_http_status": response.get("http_status"),
                "capture_trace": trace,
                "payload": None,
                "latency_ms": response.get("latency_ms", 0),
            }

        body = response.get("body")
        if not isinstance(body, dict):
            return {
                "status": "error",
                "request_id": request_id,
                "error_code": "bridge_protocol_invalid",
                "details": "bridge snapshot payload was not an object",
                "bridge_status": "error",
                "bridge_error_code": "bridge_protocol_invalid",
                "bridge_http_status": response.get("http_status"),
                "capture_trace": trace,
                "payload": None,
                "latency_ms": response.get("latency_ms", 0),
            }

        nodes = body.get("nodes")
        if not isinstance(nodes, list):
            return {
                "status": "error",
                "request_id": request_id,
                "error_code": "bridge_protocol_invalid",
                "details": "bridge snapshot payload missing nodes array",
                "bridge_status": "error",
                "bridge_error_code": "bridge_protocol_invalid",
                "bridge_http_status": response.get("http_status"),
                "capture_trace": trace,
                "payload": body,
                "latency_ms": response.get("latency_ms", 0),
            }

        return {
            "status": "ok",
            "request_id": request_id,
            "bridge_status": "ok",
            "bridge_error_code": None,
            "bridge_http_status": response.get("http_status"),
            "capture_trace": trace,
            "payload": body,
            "latency_ms": response.get("latency_ms", 0),
        }
