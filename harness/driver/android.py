from __future__ import annotations

import os
import shlex
import subprocess
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import Any

from harness.driver.android_bridge import AndroidBridgeConfig, AndroidTreeClient
from harness.driver.device_bridge import DeviceHarness
from harness.driver.selectors import build_anchor, build_ref


class AndroidDriver(DeviceHarness):
    def __init__(self, app: dict[str, Any], dispatch_commands: bool = False) -> None:
        super().__init__(platform="android", app=app, dispatch_commands=dispatch_commands)
        local_port = int(os.getenv("ANDROID_BRIDGE_LOCAL_PORT", "18765"))
        remote_port = int(os.getenv("ANDROID_BRIDGE_REMOTE_PORT", "18765"))
        timeout_seconds = float(os.getenv("ANDROID_BRIDGE_TIMEOUT_SECONDS", "3.0"))
        serial = os.getenv("ANDROID_SERIAL")
        self._bridge = AndroidTreeClient(
            AndroidBridgeConfig(
                local_port=local_port,
                remote_port=remote_port,
                timeout_seconds=timeout_seconds,
                serial=serial,
            )
        )

    def app_identity(self) -> str:
        return str(self.app.get("android_package", "android.app"))

    def preflight(self) -> dict[str, Any]:
        if not self.dispatch_commands:
            return {"status": "ok", "details": "dispatch disabled; using synthetic snapshot mode", "bridge_status": "synthetic"}
        return self._bridge.health(app_package=self.app_identity())

    def _adb_prefix(self) -> list[str]:
        prefix = ["adb"]
        serial = os.getenv("ANDROID_SERIAL")
        if serial:
            prefix.extend(["-s", serial])
        return prefix

    def snapshot(self, options: dict[str, Any] | None = None) -> dict[str, Any]:
        options = dict(options or {})
        if not self.dispatch_commands:
            return super().snapshot(options)

        if self._lightweight_snapshot_requested(options):
            capture = self._bridge.snapshot(app_package=self.app_identity(), options=options)
            if capture.get("status") == "ok":
                raw_payload = capture.get("payload")
                raw_nodes = raw_payload.get("nodes", []) if isinstance(raw_payload, dict) else []
                if isinstance(raw_nodes, list) and raw_nodes:
                    return self._normalize_bridge_snapshot(capture, options=options)

                adb_capture = self._adb_snapshot()
                if adb_capture.get("status") == "ok":
                    capture = dict(capture)
                    capture["error_code"] = "bridge_empty_tree"
                    capture["details"] = "bridge returned empty node list"
                    capture["bridge_status"] = "error"
                    capture["bridge_error_code"] = "bridge_empty_tree"
                    return self._normalize_adb_fallback(adb_capture, bridge_capture=capture, options=options)

                return self._synthetic_snapshot_fallback(
                    options,
                    bridge_capture=dict(
                        capture,
                        error_code="bridge_empty_tree",
                        details="bridge returned empty node list",
                        bridge_status="error",
                        bridge_error_code="bridge_empty_tree",
                    ),
                    adb_capture=adb_capture,
                )

            adb_capture = self._adb_snapshot()
            if adb_capture.get("status") == "ok":
                return self._normalize_adb_fallback(adb_capture, bridge_capture=capture, options=options)

            return self._synthetic_snapshot_fallback(options, bridge_capture=capture, adb_capture=adb_capture)

        adb_capture = self._adb_snapshot()
        if adb_capture.get("status") == "ok":
            return self._normalize_adb_snapshot(adb_capture, options=options)

        capture = self._bridge.snapshot(app_package=self.app_identity(), options=options)
        if capture.get("status") != "ok":
            return self._synthetic_snapshot_fallback(options, bridge_capture=capture, adb_capture=adb_capture)

        return self._normalize_bridge_snapshot(capture, options=options)

    @staticmethod
    def _snapshot_request_metadata(options: dict[str, Any] | None = None) -> dict[str, bool]:
        options = dict(options or {})
        return {
            "interactive_only": AndroidDriver._to_bool(options.get("interactive_only"), False),
            "compact": AndroidDriver._to_bool(options.get("compact"), False),
        }

    @classmethod
    def _lightweight_snapshot_requested(cls, options: dict[str, Any] | None = None) -> bool:
        request = cls._snapshot_request_metadata(options)
        return request["interactive_only"] or request["compact"]

    def _apply_snapshot_request(self, snapshot: dict[str, Any], options: dict[str, Any] | None = None) -> dict[str, Any]:
        request = self._snapshot_request_metadata(options)
        snapshot["snapshot_request"] = request

        report = snapshot.get("normalization_report")
        if not isinstance(report, dict):
            report = {}
        report["interactive_only_requested"] = request["interactive_only"]
        report["compact_requested"] = request["compact"]

        if request["interactive_only"]:
            elements = [
                element
                for element in snapshot.get("elements", [])
                if isinstance(element, dict) and element.get("interactive")
            ]
            snapshot["elements"] = elements
            snapshot["root"] = elements[0]["ref"] if elements else "root"
            snapshot["tree_hash"] = self._tree_hash(elements)
            snapshot["element_map"] = {el["id"]: el["ref"] for el in elements if el.get("id")}
            report["interactive_only_applied"] = True
            report["filtered_node_count"] = len(elements)

        snapshot["normalization_report"] = report
        return snapshot

    @staticmethod
    def _bridge_error_details(
        capture: dict[str, Any],
        *,
        error_code: str | None = None,
        details: str | None = None,
    ) -> dict[str, Any]:
        return {
            "error_code": error_code or capture.get("error_code"),
            "details": details or capture.get("details"),
            "bridge_status": capture.get("bridge_status"),
            "bridge_error_code": capture.get("bridge_error_code"),
            "bridge_http_status": capture.get("bridge_http_status"),
        }

    def _normalize_adb_fallback(
        self,
        adb_capture: dict[str, Any],
        *,
        bridge_capture: dict[str, Any],
        options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        snapshot = self._normalize_adb_snapshot(adb_capture, options=options)
        snapshot["capture_source"] = "adb_uiautomator_fallback"
        snapshot["capture_error"] = self._bridge_error_details(bridge_capture)
        snapshot["raw_tree"] = bridge_capture.get("payload")
        trace = snapshot.get("capture_trace")
        if not isinstance(trace, dict):
            trace = {}
        trace["bridge_snapshot"] = bridge_capture.get("capture_trace")
        snapshot["capture_trace"] = trace
        return snapshot

    def _synthetic_snapshot_fallback(
        self,
        options: dict[str, Any] | None,
        *,
        bridge_capture: dict[str, Any],
        adb_capture: dict[str, Any] | None = None,
        error_code: str | None = None,
        details: str | None = None,
    ) -> dict[str, Any]:
        fallback = super().snapshot(options)
        fallback = self._apply_snapshot_request(fallback, options)
        fallback["capture_source"] = "bridge_error_fallback"
        fallback["capture_latency_ms"] = int(bridge_capture.get("latency_ms", 0))
        fallback["source_request_id"] = bridge_capture.get("request_id")
        fallback["capture_error"] = self._bridge_error_details(
            bridge_capture,
            error_code=error_code,
            details=details,
        )
        if isinstance(adb_capture, dict) and adb_capture.get("status") != "ok":
            fallback["capture_error"]["adb_error_code"] = adb_capture.get("error_code")
            fallback["capture_error"]["adb_details"] = adb_capture.get("details")
        trace = {"bridge_snapshot": bridge_capture.get("capture_trace")}
        if isinstance(adb_capture, dict):
            trace["adb_snapshot"] = adb_capture
        fallback["capture_trace"] = trace
        fallback["raw_tree"] = bridge_capture.get("payload")
        return fallback

    def _adb_snapshot(self) -> dict[str, Any]:
        """Capture UI snapshot using ADB uiautomator."""
        try:
            # Dump UI hierarchy to file
            dump_result = subprocess.run(
                self._adb_prefix() + ["shell", "uiautomator", "dump", "/sdcard/window_dump.xml"],
                capture_output=True, text=True, timeout=10
            )
            if dump_result.returncode != 0:
                return {"status": "error", "error_code": "adb_dump_failed", "details": dump_result.stderr}

            # Read the dump file
            cat_result = subprocess.run(
                self._adb_prefix() + ["shell", "cat", "/sdcard/window_dump.xml"],
                capture_output=True, text=True, timeout=10
            )
            if cat_result.returncode != 0:
                return {"status": "error", "error_code": "adb_cat_failed", "details": cat_result.stderr}

            # Parse XML
            xml_content = cat_result.stdout
            if not xml_content or "<hierarchy" not in xml_content:
                return {"status": "error", "error_code": "empty_xml", "details": "No XML content returned"}

            return {
                "status": "ok",
                "xml": xml_content,
                "request_id": "adb-snapshot",
            }
        except subprocess.TimeoutExpired:
            return {"status": "error", "error_code": "adb_timeout", "details": "ADB command timed out"}
        except Exception as e:
            return {"status": "error", "error_code": "adb_exception", "details": str(e)}

    def _normalize_adb_snapshot(
        self,
        capture: dict[str, Any],
        options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Normalize ADB uiautomator snapshot to cat.v2 format."""
        xml_content = capture.get("xml", "")

        try:
            root = ET.fromstring(xml_content)
        except ET.ParseError as e:
            snapshot = {
                "schema_version": "cat.v2",
                "platform": self.platform,
                "captured_at": datetime.now(timezone.utc).isoformat(),
                "root": "root",
                "elements": [],
                "capture_source": "adb_parse_error",
                "capture_error": {"error_code": "xml_parse_error", "details": str(e)},
            }
            return self._apply_snapshot_request(snapshot, options)

        elements = []
        node_index = 0

        def parse_bounds(bounds_str: str) -> list[int]:
            """Parse bounds string [left,top][right,bottom] to list."""
            try:
                parts = bounds_str.replace("[", ",").replace("]", ",").split(",")
                nums = [int(p) for p in parts if p.strip()]
                if len(nums) >= 4:
                    return nums[:4]
            except:
                pass
            return [0, 0, 0, 0]

        def traverse(node: ET.Element, path: str, depth: int) -> None:
            nonlocal node_index

            bounds = parse_bounds(node.get("bounds", ""))
            text = node.get("text", "")
            resource_id = node.get("resource-id", "")
            class_name = node.get("class", "android.view.View")
            content_desc = node.get("content-desc", "")
            clickable = node.get("clickable", "false") == "true"
            enabled = node.get("enabled", "true") != "false"
            visible = node.get("visible-to-user", "true") != "false"
            focusable = node.get("focusable", "false") == "true"
            checked = node.get("checked", "false") == "true"
            selected = node.get("selected", "false") == "true"
            editable = "Edit" in class_name

            label = content_desc or text or resource_id or class_name
            interactive = clickable or focusable or editable

            element = {
                "id": resource_id or f"node-{node_index}",
                "label": label,
                "type": class_name,
                "text": text,
                "path": path,
                "ordinal": node_index,
                "interactive": interactive,
                "class_name": class_name,
                "resource_id": resource_id,
                "content_desc": content_desc,
                "bounds": bounds,
                "clickable": clickable,
                "enabled": enabled,
                "visible": visible,
                "focusable": focusable,
                "checked": checked,
                "selected": selected,
                "editable": editable,
                "depth": depth,
                "index_in_parent": node_index,
                "source_node_id": f"node-{node_index}",
            }
            element["ref"] = build_ref(self.platform, element)
            element["anchor"] = build_anchor(element)
            elements.append(element)

            node_index += 1

            for idx, child in enumerate(node):
                traverse(child, f"{path}/{idx}", depth + 1)

        # Start traversal from hierarchy root
        for idx, child in enumerate(root):
            traverse(child, f"0/{idx}", 0)

        snapshot = {
            "schema_version": "cat.v2",
            "platform": self.platform,
            "captured_at": datetime.now(timezone.utc).isoformat(),
            "root": elements[0]["ref"] if elements else "root",
            "elements": elements,
            "tree_hash": self._tree_hash(elements),
            "element_map": {el["id"]: el["ref"] for el in elements if el.get("id")},
            "capture_source": "adb_uiautomator",
            "source_request_id": capture.get("request_id"),
            "capture_trace": {"adb_dump": "success"},
        }
        return self._apply_snapshot_request(snapshot, options)

    def command_for_action(self, action: dict[str, Any]) -> str | None:
        op = action.get("action")
        package = str(self.app.get("android_package", ""))

        if op == "launch_app":
            adb_prefix = " ".join(shlex.quote(part) for part in self._adb_prefix())
            quoted_package = shlex.quote(package)
            return (
                f'component=$({adb_prefix} shell cmd package resolve-activity --brief {quoted_package} | tail -n 1 | tr -d "\\r"); '
                f'if [ -n "$component" ]; then {adb_prefix} shell am start -W "$component"; '
                f'else {adb_prefix} shell monkey -p {quoted_package} -c android.intent.category.LAUNCHER 1; fi'
            )

        if op == "tap":
            if "x" in action and "y" in action:
                return f"adb shell input tap {int(action['x'])} {int(action['y'])}"
            return None

        if op == "input_text":
            text = str(action.get("text", ""))
            # ADB input text uses %s for spaces
            text = text.replace(" ", "%s")
            text = shlex.quote(text)
            return f"adb shell input text {text}"

        if op == "swipe":
            return (
                "adb shell input swipe "
                f"{int(action.get('x1', 100))} {int(action.get('y1', 200))} "
                f"{int(action.get('x2', 100))} {int(action.get('y2', 600))} {int(action.get('duration_ms', 300))}"
            )

        if op == "wait":
            return f"sleep {float(action.get('seconds', 1))}"

        if op in {"assert_visible", "assert_eventually", "expect_transition"}:
            return None

        return None

    def interact(
        self,
        action: dict[str, Any],
        *,
        elements: list[dict[str, Any]] | None = None,
        snapshot: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        result = super().interact(action, elements=elements, snapshot=snapshot)
        if not self.dispatch_commands:
            return result

        op = str(action.get("action", ""))
        if op in {"wait", "assert_visible", "assert_eventually", "expect_transition"}:
            return result

        health = self.preflight()
        result["bridge_status"] = health.get("bridge_status")
        result["bridge_error_code"] = health.get("bridge_error_code")
        result["bridge_http_status"] = health.get("bridge_http_status")
        if health.get("status") != "ok" and result.get("status") not in {"error", "fail"}:
            result["status"] = "error"
            result["error_code"] = health.get("error_code", "bridge_not_integrated")
            result["details"] = health.get("details", "android bridge is not ready")
            result["capture_trace"] = health.get("capture_trace")
        return result

    @staticmethod
    def _to_bool(value: Any, default: bool = False) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return value != 0
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"true", "1", "yes", "y", "on"}:
                return True
            if normalized in {"false", "0", "no", "n", "off"}:
                return False
        return default

    @staticmethod
    def _to_int(value: Any, default: int = 0) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    @classmethod
    def _normalize_bounds(cls, value: Any) -> list[int]:
        if isinstance(value, list) and len(value) == 4:
            return [cls._to_int(item, 0) for item in value]
        if isinstance(value, dict):
            return [
                cls._to_int(value.get("left"), 0),
                cls._to_int(value.get("top"), 0),
                cls._to_int(value.get("right"), 0),
                cls._to_int(value.get("bottom"), 0),
            ]
        if isinstance(value, str):
            material = value.replace("[", ",").replace("]", ",")
            parts = [item for item in material.split(",") if item.strip()]
            if len(parts) >= 4:
                return [cls._to_int(parts[0], 0), cls._to_int(parts[1], 0), cls._to_int(parts[2], 0), cls._to_int(parts[3], 0)]
        return [0, 0, 0, 0]

    def _normalize_bridge_snapshot(
        self,
        capture: dict[str, Any],
        options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        raw_payload = capture.get("payload")
        if not isinstance(raw_payload, dict):
            return self._synthetic_snapshot_fallback(
                options,
                bridge_capture=capture,
                error_code="bridge_protocol_invalid",
                details="bridge payload was not an object",
            )

        raw_nodes = raw_payload.get("nodes", [])
        if not isinstance(raw_nodes, list) or not raw_nodes:
            return self._synthetic_snapshot_fallback(
                options,
                bridge_capture=capture,
                error_code="bridge_empty_tree",
                details="bridge returned empty node list",
            )

        nodes_by_id: dict[str, dict[str, Any]] = {}
        children: dict[str, list[str]] = {}
        dropped_nodes = 0
        for idx, raw_node in enumerate(raw_nodes):
            if not isinstance(raw_node, dict):
                dropped_nodes += 1
                continue
            source_id = str(
                raw_node.get("node_id")
                or raw_node.get("source_node_id")
                or raw_node.get("id")
                or raw_node.get("uid")
                or f"node-{idx}"
            )
            parent_id_raw = raw_node.get("parent_id")
            if parent_id_raw is None:
                parent_id_raw = raw_node.get("parent")
            parent_id = str(parent_id_raw) if parent_id_raw is not None else None
            node = {
                "source_node_id": source_id,
                "parent_id": parent_id,
                "class_name": str(raw_node.get("class_name") or raw_node.get("class") or "android.view.View"),
                "resource_id": str(raw_node.get("resource_id") or raw_node.get("view_id_resource_name") or ""),
                "semantic_id": str(raw_node.get("semantic_id") or ""),
                "screen_id": str(raw_node.get("screen_id") or ""),
                "text": str(raw_node.get("text") or ""),
                "label": str(raw_node.get("label") or ""),
                "content_desc": str(raw_node.get("content_desc") or raw_node.get("contentDescription") or ""),
                "bounds": self._normalize_bounds(raw_node.get("bounds")),
                "clickable": self._to_bool(raw_node.get("clickable"), False),
                "enabled": self._to_bool(raw_node.get("enabled"), True),
                "visible": self._to_bool(raw_node.get("visible"), True),
                "focusable": self._to_bool(raw_node.get("focusable"), False),
                "checked": self._to_bool(raw_node.get("checked"), False),
                "selected": self._to_bool(raw_node.get("selected"), False),
                "editable": self._to_bool(raw_node.get("editable"), False),
                "index_in_parent": self._to_int(
                    raw_node.get("index_in_parent", raw_node.get("index", raw_node.get("ordinal", 0))),
                    0,
                ),
            }
            nodes_by_id[source_id] = node
            if parent_id:
                children.setdefault(parent_id, []).append(source_id)

        if not nodes_by_id:
            return self._synthetic_snapshot_fallback(
                options,
                bridge_capture=capture,
                error_code="bridge_empty_tree",
                details="bridge returned no valid nodes",
            )

        root_id = str(raw_payload.get("root") or raw_payload.get("root_id") or "")
        if root_id not in nodes_by_id:
            candidates = [node_id for node_id, node in nodes_by_id.items() if not node.get("parent_id")]
            root_id = sorted(candidates)[0] if candidates else sorted(nodes_by_id.keys())[0]

        ordered_elements: list[dict[str, Any]] = []
        visited: set[str] = set()

        def walk(node_id: str, path: str, depth: int) -> None:
            if node_id in visited:
                return
            node = nodes_by_id.get(node_id)
            if not node:
                return
            visited.add(node_id)

            label = (
                node["label"]
                or node["content_desc"]
                or node["text"]
                or node["semantic_id"]
                or node["resource_id"]
                or node["class_name"]
                or node["source_node_id"]
            )
            node_type = node["class_name"] or "android.view.View"
            interactive = bool(node["clickable"] or node["focusable"] or node["editable"])
            element = {
                "id": node["resource_id"] or node["source_node_id"],
                "label": label,
                "type": node_type,
                "text": node["text"],
                "path": path,
                "ordinal": len(ordered_elements),
                "interactive": interactive,
                "class_name": node["class_name"],
                "semantic_id": node["semantic_id"] or None,
                "screen_id": node["screen_id"] or None,
                "resource_id": node["resource_id"],
                "content_desc": node["content_desc"],
                "bounds": node["bounds"],
                "clickable": node["clickable"],
                "enabled": node["enabled"],
                "visible": node["visible"],
                "focusable": node["focusable"],
                "checked": node["checked"],
                "selected": node["selected"],
                "editable": node["editable"],
                "depth": depth,
                "index_in_parent": node["index_in_parent"],
                "source_node_id": node["source_node_id"],
            }
            element["ref"] = build_ref(self.platform, element)
            element["anchor"] = build_anchor(element)
            ordered_elements.append(element)

            children_ids = children.get(node_id, [])
            children_ids.sort(key=lambda item: (nodes_by_id[item]["index_in_parent"], item))
            for idx, child_id in enumerate(children_ids):
                walk(child_id, f"{path}/{idx}", depth + 1)

        walk(root_id, "0", 0)
        for node_id in sorted(nodes_by_id):
            if node_id not in visited:
                walk(node_id, f"9/{len(ordered_elements)}", 1)

        tree_hash = self._tree_hash(ordered_elements)
        diagnostics = raw_payload.get("diagnostics", {})
        warnings = []
        if isinstance(diagnostics, dict):
            diagnostics_warnings = diagnostics.get("warnings", [])
            if isinstance(diagnostics_warnings, list):
                warnings = [str(item) for item in diagnostics_warnings]

        snapshot = {
            "schema_version": "cat.v2",
            "platform": self.platform,
            "captured_at": datetime.now(timezone.utc).isoformat(),
            "root": ordered_elements[0]["ref"],
            "screen_id": str(raw_payload.get("screen_id") or nodes_by_id[root_id].get("screen_id") or ""),
            "elements": ordered_elements,
            "tree_hash": tree_hash,
            "element_map": {el["id"]: el["ref"] for el in ordered_elements if el.get("id")},
            "capture_source": "android_accessibility_bridge",
            "capture_latency_ms": int(capture.get("latency_ms", 0)),
            "source_request_id": capture.get("request_id"),
            "normalization_report": {
                "version": str(raw_payload.get("protocol_version", "bridge.v1")),
                "raw_node_count": len(raw_nodes),
                "normalized_node_count": len(ordered_elements),
                "dropped_nodes": dropped_nodes,
                "warnings": warnings,
            },
            "raw_tree": raw_payload,
            "capture_trace": capture.get("capture_trace"),
        }
        return self._apply_snapshot_request(snapshot, options)
