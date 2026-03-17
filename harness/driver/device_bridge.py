from __future__ import annotations

import re
import subprocess
import time
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any

from harness.driver.selectors import build_anchor, build_ref, resolve_selector

SEMANTIC_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)+$")


class DeviceHarness(ABC):
    def __init__(self, platform: str, app: dict[str, Any], dispatch_commands: bool = False) -> None:
        self.platform = platform
        self.app = app
        self.dispatch_commands = dispatch_commands
        self._visible_targets: set[str] = set()
        self._input_values: dict[str, str] = {}
        self._last_action: str | None = None
        self._seed_state()

    @abstractmethod
    def command_for_action(self, action: dict[str, Any]) -> str | None:
        raise NotImplementedError

    @abstractmethod
    def app_identity(self) -> str:
        raise NotImplementedError

    def _seed_state(self) -> None:
        self._visible_targets = {"launch_screen"}

    def preflight(self) -> dict[str, Any]:
        return {"status": "ok", "details": "no preflight checks"}

    def snapshot(self, options: dict[str, Any] | None = None) -> dict[str, Any]:
        _ = options or {}
        elements = self._build_elements()
        snapshot = {
            "schema_version": "cat.v2",
            "platform": self.platform,
            "captured_at": datetime.now(timezone.utc).isoformat(),
            "root": elements[0]["ref"],
            "elements": elements,
            "tree_hash": self._tree_hash(elements),
            "element_map": {el["id"]: el["ref"] for el in elements if el.get("id")},
            "capture_source": "synthetic_state_model",
            "capture_latency_ms": 0,
            "source_request_id": None,
            "normalization_report": {
                "version": "synthetic.v1",
                "warnings": [],
            },
            "capture_trace": {
                "capture_source": "synthetic_state_model",
                "details": "snapshot generated from local harness state",
            },
        }
        screen_id = self._screen_id_for_snapshot(elements)
        if screen_id:
            snapshot["screen_id"] = screen_id
        return snapshot

    def diff(self, before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
        before_map = {el["ref"]: el for el in before.get("elements", [])}
        after_map = {el["ref"]: el for el in after.get("elements", [])}

        added = sorted(ref for ref in after_map if ref not in before_map)
        removed = sorted(ref for ref in before_map if ref not in after_map)

        changes: list[dict[str, Any]] = []
        for ref in added:
            changes.append(
                {
                    "type": "node_added",
                    "ref": ref,
                    "before": None,
                    "after": after_map.get(ref),
                    "source_fields": [],
                }
            )
        for ref in removed:
            changes.append(
                {
                    "type": "node_removed",
                    "ref": ref,
                    "before": before_map.get(ref),
                    "after": None,
                    "source_fields": [],
                }
            )

        attr_fields = {"id", "label", "type", "text", "resource_id", "content_desc", "class_name", "screen_id", "semantic_id"}
        state_fields = {
            "interactive",
            "clickable",
            "enabled",
            "visible",
            "focusable",
            "checked",
            "selected",
            "editable",
        }
        common_refs = sorted(set(before_map).intersection(after_map))
        for ref in common_refs:
            left = before_map[ref]
            right = after_map[ref]

            attr_changes = [field for field in sorted(attr_fields) if left.get(field) != right.get(field)]
            if attr_changes:
                changes.append(
                    {
                        "type": "attr_changed",
                        "ref": ref,
                        "before": {field: left.get(field) for field in attr_changes},
                        "after": {field: right.get(field) for field in attr_changes},
                        "source_fields": attr_changes,
                    }
                )

            if left.get("bounds") != right.get("bounds"):
                changes.append(
                    {
                        "type": "bounds_changed",
                        "ref": ref,
                        "before": {"bounds": left.get("bounds")},
                        "after": {"bounds": right.get("bounds")},
                        "source_fields": ["bounds"],
                    }
                )

            changed_state = [field for field in sorted(state_fields) if left.get(field) != right.get(field)]
            if changed_state:
                changes.append(
                    {
                        "type": "state_changed",
                        "ref": ref,
                        "before": {field: left.get(field) for field in changed_state},
                        "after": {field: right.get(field) for field in changed_state},
                        "source_fields": changed_state,
                    }
                )

        before_source = {
            str(item["source_node_id"]): item
            for item in before_map.values()
            if item.get("source_node_id") is not None
        }
        after_source = {
            str(item["source_node_id"]): item
            for item in after_map.values()
            if item.get("source_node_id") is not None
        }
        for source_id in sorted(set(before_source).intersection(after_source)):
            left = before_source[source_id]
            right = after_source[source_id]
            if left.get("ref") != right.get("ref"):
                changes.append(
                    {
                        "type": "subtree_moved",
                        "ref": right.get("ref"),
                        "before": {"ref": left.get("ref"), "path": left.get("path")},
                        "after": {"ref": right.get("ref"), "path": right.get("path")},
                        "source_fields": ["path"],
                    }
                )

        change_types = sorted({item["type"] for item in changes})
        return {
            "schema_version": "cat.diff.v2",
            "before_tree_hash": before.get("tree_hash"),
            "after_tree_hash": after.get("tree_hash"),
            "change_count": len(changes),
            "change_types": change_types,
            "changes": changes,
        }

    def interact(
        self,
        action: dict[str, Any],
        *,
        elements: list[dict[str, Any]] | None = None,
        snapshot: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        op = action.get("action", "")
        selector = action.get("selector")
        selector_info: dict[str, Any] | None = None
        resolved: dict[str, Any] | None = None
        action_payload = dict(action)

        if selector:
            if snapshot is None and elements is None:
                snapshot = self.snapshot()
            if elements is None and isinstance(snapshot, dict):
                elements = snapshot.get("elements", [])

            resolved, info = resolve_selector(selector, elements or [])
            selector_info = dict(info)
            if resolved is None:
                match_type = str(selector_info.get("match_type", ""))
                error_code = "ambiguous_selector" if match_type in {"ambiguous", "ambiguous_within"} else "selector_drift"
                return {
                    "status": "error",
                    "details": f"selector not found: {selector}",
                    "error_code": error_code,
                    "selector": selector,
                    "selector_info": selector_info,
                    "candidates": selector_info.get("candidates", []),
                    "command": None,
                }
            selector_info["resolved_ref"] = resolved.get("ref")

        if op == "tap":
            if "x" not in action_payload or "y" not in action_payload:
                if resolved is None:
                    return {
                        "status": "error",
                        "details": "tap requires x/y or a selector with bounds",
                        "error_code": "missing_coordinates",
                        "selector": selector,
                        "selector_info": selector_info,
                        "command": None,
                    }
                coords = self._center_from_bounds(resolved.get("bounds"))
                if coords is None:
                    return {
                        "status": "error",
                        "details": "tap selector did not resolve valid bounds",
                        "error_code": "missing_coordinates",
                        "selector": selector,
                        "selector_info": selector_info,
                        "command": None,
                    }
                action_payload["x"], action_payload["y"] = coords
                if selector_info is not None:
                    selector_info["tap_coordinates"] = {"x": action_payload["x"], "y": action_payload["y"]}

        command = self.command_for_action(action_payload)
        if command is None:
            # Assertion actions are handled in verify() and don't dispatch a command.
            if op in {"assert_visible", "assert_eventually", "expect_transition"}:
                return {"status": "ok", "details": "assertion action uses verification loop", "command": None}
            return {"status": "error", "details": f"unsupported action: {op}", "command": None}

        result = self._run_or_record(command)
        if result.get("status") not in {"error", "fail"}:
            self._apply_state_transition(action_payload)
        self._last_action = op

        if selector_info:
            result["selector_info"] = selector_info
        return result

    def verify(self, assertion: dict[str, Any]) -> dict[str, Any]:
        selector = assertion.get("selector")
        timeout_ms = int(assertion.get("timeout_ms", assertion.get("timeout", 0) * 1000 or 5000))
        poll_ms = int(assertion.get("poll_ms", 250))
        started = time.monotonic()
        expected_value = assertion.get("value")
        expected_text = "" if expected_value is None else str(expected_value)
        last_actual: str | None = None

        while True:
            snapshot = self.snapshot()
            elements = snapshot.get("elements", [])
            target = None
            selector_info: dict[str, Any] | None = None

            if selector:
                target, selector_info = resolve_selector(selector, elements)
            elif assertion.get("target"):
                selector = {"by": "id", "value": str(assertion["target"])}
                target, selector_info = resolve_selector(selector, elements)

            if target is not None:
                actual = self._primary_actual(target)
                last_actual = actual
                if self._expectation_satisfied(target, expected_text):
                    return {
                        "status": "ok",
                        "verdict": "pass",
                        "expected": expected_text or "visible",
                        "actual": actual,
                        "selector": selector,
                        "selector_info": selector_info,
                        "snapshot_tree_hash": snapshot.get("tree_hash"),
                    }

            elapsed_ms = int((time.monotonic() - started) * 1000)
            if elapsed_ms >= timeout_ms:
                if target is not None:
                    return {
                        "status": "fail",
                        "verdict": "fail",
                        "error_code": "assertion_mismatch",
                        "details": "assertion expected value did not match resolved element",
                        "expected": expected_text or "visible",
                        "actual": last_actual,
                        "selector": selector,
                        "elapsed_ms": elapsed_ms,
                    }
                return {
                    "status": "fail",
                    "verdict": "fail",
                    "error_code": "assertion_timeout",
                    "details": "assertion condition was not met before timeout",
                    "selector": selector,
                    "elapsed_ms": elapsed_ms,
                }

            remaining_seconds = max(0.0, (timeout_ms - elapsed_ms) / 1000.0)
            sleep_seconds = min(max(poll_ms, 0) / 1000.0, remaining_seconds)
            if sleep_seconds > 0:
                time.sleep(sleep_seconds)

    def replay(self, script: list[dict[str, Any]]) -> dict[str, Any]:
        trace: list[dict[str, Any]] = []
        for step in script:
            before = self.snapshot()
            interact_result = self.interact(step)
            after = self.snapshot()
            trace.append(
                {
                    "action": step.get("action"),
                    "result": interact_result,
                    "before_tree_hash": before.get("tree_hash"),
                    "after_tree_hash": after.get("tree_hash"),
                }
            )
        return {"status": "ok", "trace": trace}

    def wait_for_state_settle(
        self,
        *,
        timeout_ms: int = 1000,
        poll_ms: int = 100,
        stable_observations: int = 2,
        snapshot_options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        started = time.monotonic()
        attempts = 0
        observed_stable = 0
        previous_fingerprint: tuple[Any, ...] | None = None
        last_snapshot: dict[str, Any] = {}

        while True:
            snapshot = self.snapshot(snapshot_options)
            last_snapshot = snapshot if isinstance(snapshot, dict) else {}
            attempts += 1
            fingerprint = self._snapshot_fingerprint(last_snapshot)

            if previous_fingerprint is not None and fingerprint == previous_fingerprint:
                observed_stable += 1
            else:
                observed_stable = 1
            previous_fingerprint = fingerprint

            elapsed_ms = int((time.monotonic() - started) * 1000)
            if observed_stable >= max(1, stable_observations):
                return {
                    "status": "settled",
                    "attempts": attempts,
                    "elapsed_ms": elapsed_ms,
                    "stable_observations": observed_stable,
                    "tree_hash": last_snapshot.get("tree_hash"),
                    "screen_id": last_snapshot.get("screen_id"),
                    "root": last_snapshot.get("root"),
                    "snapshot": last_snapshot,
                }

            if elapsed_ms >= timeout_ms:
                return {
                    "status": "timeout",
                    "attempts": attempts,
                    "elapsed_ms": elapsed_ms,
                    "stable_observations": observed_stable,
                    "tree_hash": last_snapshot.get("tree_hash"),
                    "screen_id": last_snapshot.get("screen_id"),
                    "root": last_snapshot.get("root"),
                    "snapshot": last_snapshot,
                }

            remaining_seconds = max(0.0, (timeout_ms - elapsed_ms) / 1000.0)
            sleep_seconds = min(max(poll_ms, 0) / 1000.0, remaining_seconds)
            if sleep_seconds > 0:
                time.sleep(sleep_seconds)

    def dump_state(self) -> dict[str, Any]:
        return {
            "visible_targets": sorted(self._visible_targets),
            "input_values": dict(self._input_values),
            "last_action": self._last_action,
        }

    def restore_state(self, payload: dict[str, Any]) -> None:
        visible_targets = payload.get("visible_targets", [])
        if isinstance(visible_targets, list) and visible_targets:
            self._visible_targets = {str(item) for item in visible_targets}

        input_values = payload.get("input_values", {})
        if isinstance(input_values, dict):
            self._input_values = {str(key): str(value) for key, value in input_values.items()}

        last_action = payload.get("last_action")
        self._last_action = str(last_action) if last_action else None

    def _run_or_record(self, command: str) -> dict[str, Any]:
        if not self.dispatch_commands:
            return {
                "status": "recorded",
                "details": "dispatch disabled",
                "command": command,
            }

        completed = subprocess.run(command, shell=True, capture_output=True, text=True, check=False)
        status = "ok" if completed.returncode == 0 else "error"
        return {
            "status": status,
            "command": command,
            "returncode": completed.returncode,
            "stdout": completed.stdout.strip(),
            "stderr": completed.stderr.strip(),
        }

    def _apply_state_transition(self, action: dict[str, Any]) -> None:
        op = action.get("action")
        if op == "launch_app":
            self._visible_targets = {"home_screen", "nav_bar", "search_box"}
            return

        if op == "tap":
            selector = action.get("selector")
            target = action.get("target")
            if isinstance(selector, dict):
                self._visible_targets.add(str(selector.get("value", "tapped_element")))
            elif target:
                self._visible_targets.add(str(target))
            self._visible_targets.add("tap_feedback")
            return

        if op == "input_text":
            text = str(action.get("text", ""))
            selector = action.get("selector")
            if isinstance(selector, dict):
                key = str(selector.get("value", "input"))
            else:
                key = str(action.get("target", "input"))
            self._input_values[key] = text
            self._visible_targets.add(key)
            return

    def _build_elements(self) -> list[dict[str, Any]]:
        nodes: list[dict[str, Any]] = []
        current_screen_id = self._current_screen_id()
        root = {
            "id": "root",
            "label": self.app_identity(),
            "type": "root",
            "text": "",
            "path": "0",
            "ordinal": 0,
            "interactive": False,
            "class_name": "root",
            "resource_id": "root",
            "content_desc": self.app_identity(),
            "bounds": [0, 0, 0, 0],
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
        }
        if current_screen_id:
            root["screen_id"] = current_screen_id
        root["ref"] = build_ref(self.platform, root)
        root["anchor"] = build_anchor(root)
        nodes.append(root)

        for idx, target in enumerate(sorted(self._visible_targets), start=1):
            node_type = "input" if target in self._input_values else "view"
            node = {
                "id": target,
                "label": target.replace("_", " ").title(),
                "type": node_type,
                "text": self._input_values.get(target, ""),
                "path": f"0/{idx}",
                "ordinal": idx,
                "interactive": node_type == "input" or target not in {"home_screen", "launch_screen"},
                "class_name": "android.widget.EditText" if node_type == "input" else "android.view.View",
                "resource_id": target,
                "content_desc": target.replace("_", " "),
                "bounds": [0, idx * 40, 1080, (idx * 40) + 30],
                "clickable": node_type != "input",
                "enabled": True,
                "visible": True,
                "focusable": node_type == "input",
                "checked": False,
                "selected": False,
                "editable": node_type == "input",
                "depth": 1,
                "index_in_parent": idx,
                "source_node_id": target,
            }
            node_screen_id = target if target.endswith("_screen") else current_screen_id
            if node_screen_id:
                node["screen_id"] = node_screen_id
            semantic_id = self._semantic_id_for_target(target)
            if semantic_id:
                node["semantic_id"] = semantic_id
            node["ref"] = build_ref(self.platform, node)
            node["anchor"] = build_anchor(node)
            nodes.append(node)
        return nodes

    def _current_screen_id(self) -> str | None:
        screen_targets = sorted(target for target in self._visible_targets if target.endswith("_screen"))
        if not screen_targets:
            return None
        non_launch = [target for target in screen_targets if target != "launch_screen"]
        return non_launch[0] if non_launch else screen_targets[0]

    @staticmethod
    def _semantic_id_for_target(target: str) -> str | None:
        return target if SEMANTIC_ID_PATTERN.fullmatch(target) else None

    def _screen_id_for_snapshot(self, elements: list[dict[str, Any]]) -> str | None:
        explicit = [str(element.get("screen_id")) for element in elements if isinstance(element, dict) and element.get("screen_id")]
        if explicit:
            return explicit[0]
        return self._current_screen_id()

    @staticmethod
    def _center_from_bounds(bounds: Any) -> tuple[int, int] | None:
        if not isinstance(bounds, list) or len(bounds) != 4:
            return None
        try:
            left, top, right, bottom = [int(value) for value in bounds]
        except (TypeError, ValueError):
            return None
        if right < left or bottom < top:
            return None
        return (left + right) // 2, (top + bottom) // 2

    @staticmethod
    def _tree_hash(elements: list[dict[str, Any]]) -> str:
        material = "|".join(
            [
                f"{el.get('ref')}:{el.get('id')}:{el.get('text')}:{el.get('path')}"
                for el in sorted(elements, key=lambda item: str(item.get("path", "")))
            ]
        )
        return build_ref("tree", {"id": material, "label": "", "type": "", "path": "", "ordinal": 0})

    @staticmethod
    def _snapshot_fingerprint(snapshot: dict[str, Any]) -> tuple[Any, ...]:
        elements = snapshot.get("elements", [])
        element_count = len(elements) if isinstance(elements, list) else -1
        return (
            snapshot.get("tree_hash"),
            snapshot.get("screen_id"),
            snapshot.get("root"),
            element_count,
        )

    @staticmethod
    def _is_presence_expectation(expected: str) -> bool:
        normalized = expected.strip().lower()
        return normalized in {"", "visible", "exists", "present"}

    def _expectation_satisfied(self, target: dict[str, Any], expected: str) -> bool:
        if self._is_presence_expectation(expected):
            return True
        for candidate in self._actual_candidates(target):
            if candidate == expected:
                return True
        return False

    @staticmethod
    def _actual_candidates(target: dict[str, Any]) -> list[str]:
        fields = ("text", "label", "semantic_id", "screen_id", "id", "content_desc", "resource_id", "class_name", "type")
        candidates: list[str] = []
        for field in fields:
            value = target.get(field)
            if value is None:
                continue
            text = str(value)
            if text:
                candidates.append(text)
        return candidates

    def _primary_actual(self, target: dict[str, Any]) -> str:
        candidates = self._actual_candidates(target)
        return candidates[0] if candidates else ""
