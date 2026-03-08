#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import socket
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib import error, parse, request

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from harness.driver.android import AndroidDriver
from harness.driver.android_bridge import AndroidBridgeConfig, AndroidTreeClient

VM_SERVICE_PATTERN = re.compile(
    r"(?:The )?Dart VM service is listening on (http://127\.0\.0\.1:(\d+)/([^/]+)/)"
)


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return float(value)
    except ValueError:
        return default


def _extract_trace_section(payload: dict[str, Any] | None, key: str) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None
    section = payload.get(key)
    if isinstance(section, dict):
        return section
    return None


def _adb_prefix(serial: str | None) -> list[str]:
    if serial:
        return ["adb", "-s", serial]
    return ["adb"]


def _run_adb(args: list[str], serial: str | None) -> dict[str, Any]:
    cmd = _adb_prefix(serial) + args
    started = datetime.now(timezone.utc)
    try:
        completed = subprocess.run(cmd, capture_output=True, text=True, check=False)
    except FileNotFoundError as exc:
        return {
            "status": "error",
            "error_code": "adb_missing",
            "details": str(exc),
            "command": " ".join(cmd),
            "returncode": 127,
            "stdout": "",
            "stderr": str(exc),
            "latency_ms": 0,
        }
    elapsed_ms = int((datetime.now(timezone.utc) - started).total_seconds() * 1000)
    return {
        "status": "ok" if completed.returncode == 0 else "error",
        "command": " ".join(cmd),
        "returncode": completed.returncode,
        "stdout": completed.stdout.strip(),
        "stderr": completed.stderr.strip(),
        "latency_ms": elapsed_ms,
    }


def _reserve_local_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _extract_vm_service(logcat: str) -> dict[str, Any] | None:
    matches = list(VM_SERVICE_PATTERN.finditer(logcat))
    if not matches:
        return None
    match = matches[-1]
    return {
        "url": match.group(1),
        "remote_port": int(match.group(2)),
        "auth_code": match.group(3),
    }


def _vm_service_request(
    local_port: int,
    auth_code: str,
    method: str,
    params: dict[str, str] | None = None,
    timeout_seconds: float = 3.0,
) -> dict[str, Any]:
    query = f"?{parse.urlencode(params)}" if params else ""
    url = f"http://127.0.0.1:{local_port}/{auth_code}/{method}{query}"
    req = request.Request(url, method="GET")
    try:
        with request.urlopen(req, timeout=timeout_seconds) as resp:
            raw = resp.read().decode("utf-8")
            parsed = json.loads(raw) if raw else {}
            return {
                "status": "ok",
                "url": url,
                "http_status": resp.status,
                "body": parsed,
                "raw_body": raw,
            }
    except error.HTTPError as exc:
        return {
            "status": "error",
            "error_code": "vm_service_http_error",
            "details": f"vm service returned http {exc.code}",
            "url": url,
            "http_status": exc.code,
            "raw_body": exc.read().decode("utf-8", errors="replace"),
        }
    except error.URLError as exc:
        return {
            "status": "error",
            "error_code": "vm_service_unreachable",
            "details": str(exc.reason),
            "url": url,
        }
    except json.JSONDecodeError as exc:
        return {
            "status": "error",
            "error_code": "vm_service_protocol_invalid",
            "details": f"vm service returned invalid json: {exc}",
            "url": url,
        }


def _flutter_vm_snapshot(
    app: str,
    serial: str | None,
    timeout_seconds: float,
) -> dict[str, Any]:
    logcat = _run_adb(["logcat", "-d"], serial)
    if logcat["status"] != "ok":
        return {
            "status": "error",
            "error_code": "logcat_unavailable",
            "details": "failed to read logcat for vm service url",
            "logcat": logcat,
        }

    vm_service = _extract_vm_service(logcat.get("stdout", ""))
    if vm_service is None:
        return {
            "status": "error",
            "error_code": "vm_service_not_found",
            "details": "no dart vm service url found in logcat",
            "logcat": logcat,
        }

    local_port = _reserve_local_port()
    bridge = AndroidTreeClient(
        AndroidBridgeConfig(
            local_port=local_port,
            remote_port=vm_service["remote_port"],
            timeout_seconds=timeout_seconds,
            serial=serial,
        )
    )
    forward = bridge.ensure_port_forward()
    if forward.get("status") != "ok":
        return {
            "status": "error",
            "error_code": "vm_service_forward_failed",
            "details": "failed to forward vm service port",
            "vm_service": vm_service,
            "port_forward": forward,
        }

    vm_info = _vm_service_request(
        local_port,
        vm_service["auth_code"],
        "getVM",
        timeout_seconds=timeout_seconds,
    )
    if vm_info.get("status") != "ok":
        return {
            "status": "error",
            "error_code": "vm_service_get_vm_failed",
            "details": vm_info.get("details", "failed to fetch vm info"),
            "vm_service": vm_service,
            "port_forward": forward,
            "vm_info": vm_info,
        }

    isolates = vm_info.get("body", {}).get("result", {}).get("isolates", [])
    isolate_id = None
    if isinstance(isolates, list) and isolates:
        isolate_id = isolates[0].get("id")
    if not isolate_id:
        return {
            "status": "error",
            "error_code": "vm_service_isolate_missing",
            "details": "no isolate id found in vm info",
            "vm_service": vm_service,
            "port_forward": forward,
            "vm_info": vm_info,
        }

    tree = _vm_service_request(
        local_port,
        vm_service["auth_code"],
        "ext.flutter.inspector.getRootWidgetTree",
        params={"isolateId": isolate_id, "groupName": "scaffold", "fullDetails": "false"},
        timeout_seconds=timeout_seconds,
    )
    if tree.get("status") != "ok":
        return {
            "status": "error",
            "error_code": "vm_service_tree_failed",
            "details": tree.get("details", "failed to fetch flutter widget tree"),
            "vm_service": vm_service,
            "port_forward": forward,
            "vm_info": vm_info,
            "tree": tree,
        }

    root = tree.get("body", {}).get("result", {}).get("result")
    if not isinstance(root, dict):
        return {
            "status": "error",
            "error_code": "vm_service_tree_invalid",
            "details": "flutter inspector returned invalid root payload",
            "vm_service": vm_service,
            "port_forward": forward,
            "vm_info": vm_info,
            "tree": tree,
        }
    node_count = 0
    max_depth = 0

    def walk(node: Any, depth: int) -> None:
        nonlocal node_count, max_depth
        if not isinstance(node, dict):
            return
        node_count += 1
        if depth > max_depth:
            max_depth = depth
        for child in node.get("children", []) or []:
            if isinstance(child, dict):
                walk(child, depth + 1)

    walk(root, 0)

    return {
        "status": "ok",
        "app": app,
        "vm_service": vm_service,
        "port_forward": forward,
        "vm_info": vm_info,
        "isolate_id": isolate_id,
        "widget_tree": root,
        "widget_tree_stats": {"node_count": node_count, "max_depth": max_depth},
    }


def _list_listening_ports(app: str, serial: str | None) -> dict[str, Any]:
    pid_result = _run_adb(["shell", "pidof", app], serial)
    pids: set[int] = set()
    if pid_result.get("status") == "ok":
        for value in pid_result.get("stdout", "").split():
            if value.isdigit():
                pids.add(int(value))

    ss_result = _run_adb(["shell", "ss", "-lntp"], serial)
    if ss_result.get("status") != "ok":
        return {
            "status": "error",
            "error_code": "listening_ports_failed",
            "details": "failed to read listening ports",
            "pidof": pid_result,
            "ss": ss_result,
        }

    entries: list[dict[str, Any]] = []
    for line in ss_result.get("stdout", "").splitlines():
        if "LISTEN" not in line:
            continue
        pid_match = re.search(r"pid=(\d+)", line)
        pid = int(pid_match.group(1)) if pid_match else None
        if pids and pid not in pids:
            continue

        parts = line.split()
        local = parts[3] if len(parts) > 3 else ""
        host = local
        port = None
        if ":" in local:
            host, port_str = local.rsplit(":", 1)
            try:
                port = int(port_str)
            except ValueError:
                port = None
        process = None
        proc_match = re.search(r'users:\(\(\"([^\"]+)\",pid=', line)
        if proc_match:
            process = proc_match.group(1)

        entries.append(
            {
                "local": local,
                "local_host": host.strip("[]"),
                "local_port": port,
                "process": process,
                "pid": pid,
            }
        )

    return {
        "status": "ok",
        "entries": entries,
        "pidof": pid_result,
        "ss": ss_result,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Inspect Android bridge port and health status.")
    parser.add_argument("--app", required=True, help="Android package name (e.g. com.example.app)")
    parser.add_argument("--snapshot", action="store_true", help="Also request a snapshot from the bridge")
    parser.add_argument("--local-port", type=int, default=_env_int("ANDROID_BRIDGE_LOCAL_PORT", 18765))
    parser.add_argument("--remote-port", type=int, default=_env_int("ANDROID_BRIDGE_REMOTE_PORT", 18765))
    parser.add_argument("--timeout-seconds", type=float, default=_env_float("ANDROID_BRIDGE_TIMEOUT_SECONDS", 3.0))
    parser.add_argument("--serial", default=os.getenv("ANDROID_SERIAL"))
    parser.add_argument("--compact", action="store_true", help="Request compact snapshot payload")
    parser.add_argument("--interactive-only", action="store_true", help="Request only interactive nodes")
    args = parser.parse_args()

    config = AndroidBridgeConfig(
        local_port=args.local_port,
        remote_port=args.remote_port,
        timeout_seconds=args.timeout_seconds,
        serial=args.serial,
    )
    client = AndroidTreeClient(config)

    health = client.health(app_package=args.app)
    trace = _extract_trace_section(health, "capture_trace") or {}
    warnings: list[str] = []

    report: dict[str, Any] = {
        "schema_version": "android_bridge_diag.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "bridge_config": trace.get("bridge_config", config.__dict__),
        "health": health,
        "port_forward": trace.get("adb_forward"),
        "port_forward_list": trace.get("adb_forward_list"),
        "listening_ports": _list_listening_ports(args.app, args.serial),
    }

    if args.snapshot:
        bridge_snapshot = client.snapshot(
            app_package=args.app,
            options={"compact": args.compact, "interactive_only": args.interactive_only},
        )
        report["bridge_snapshot"] = bridge_snapshot
        snapshot_trace = _extract_trace_section(bridge_snapshot, "capture_trace")
        if snapshot_trace:
            report["snapshot_port_forward"] = snapshot_trace.get("adb_forward")
        if bridge_snapshot.get("status") != "ok":
            flutter_snapshot = _flutter_vm_snapshot(
                app=args.app,
                serial=args.serial,
                timeout_seconds=args.timeout_seconds,
            )
            report["flutter_vm_service"] = flutter_snapshot
            if flutter_snapshot.get("status") == "ok":
                report["flutter_widget_tree"] = flutter_snapshot.get("widget_tree")
                report["flutter_widget_tree_stats"] = flutter_snapshot.get("widget_tree_stats")
            else:
                warnings.append("bridge_snapshot_failed")
                warnings.append("flutter_vm_snapshot_failed")
            driver = AndroidDriver(app={"android_package": args.app}, dispatch_commands=True)
            fallback_snapshot = driver.snapshot(
                {"compact": args.compact, "interactive_only": args.interactive_only}
            )
            report["snapshot"] = fallback_snapshot
            report["snapshot_source"] = fallback_snapshot.get("capture_source")
            if report["snapshot_source"] != "adb_uiautomator":
                warnings.append("snapshot_fallback_not_adb")
        else:
            report["snapshot"] = bridge_snapshot
            report["snapshot_source"] = "android_accessibility_bridge"
    if warnings:
        report["warnings"] = warnings
    report["status"] = (
        "ok"
        if health.get("status") == "ok" and (not args.snapshot or "snapshot" in report)
        else "error"
    )

    print(json.dumps(report, indent=2, ensure_ascii=True))


if __name__ == "__main__":
    main()
