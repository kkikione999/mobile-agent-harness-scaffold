from __future__ import annotations

import subprocess
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any

from harness.driver.selectors import build_anchor, build_ref, resolve_selector


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

    def snapshot(self, options: dict[str, Any] | None = None) -> dict[str, Any]:
        _ = options or {}
        elements = self._build_elements()
        return {
            "schema_version": "cat.v1",
            "platform": self.platform,
            "captured_at": datetime.now(timezone.utc).isoformat(),
            "root": elements[0]["ref"],
            "elements": elements,
            "tree_hash": self._tree_hash(elements),
            "element_map": {el["id"]: el["ref"] for el in elements if el.get("id")},
        }

    def diff(self, before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
        before_map = {el["ref"]: el for el in before.get("elements", [])}
        after_map = {el["ref"]: el for el in after.get("elements", [])}

        added = sorted(ref for ref in after_map if ref not in before_map)
        removed = sorted(ref for ref in before_map if ref not in after_map)

        text_changed: list[dict[str, Any]] = []
        for ref in sorted(set(before_map).intersection(after_map)):
            before_text = str(before_map[ref].get("text", ""))
            after_text = str(after_map[ref].get("text", ""))
            if before_text != after_text:
                text_changed.append({"ref": ref, "before": before_text, "after": after_text})

        changes: list[dict[str, Any]] = []
        for ref in added:
            changes.append({"type": "node_added", "ref": ref})
        for ref in removed:
            changes.append({"type": "node_removed", "ref": ref})
        for item in text_changed:
            changes.append({"type": "text_changed", **item})

        change_types = sorted({item["type"] for item in changes})
        return {
            "schema_version": "cat.diff.v1",
            "before_tree_hash": before.get("tree_hash"),
            "after_tree_hash": after.get("tree_hash"),
            "change_count": len(changes),
            "change_types": change_types,
            "changes": changes,
        }

    def interact(self, action: dict[str, Any]) -> dict[str, Any]:
        op = action.get("action", "")
        command = self.command_for_action(action)
        selector = action.get("selector")
        selector_info: dict[str, Any] | None = None

        if selector:
            current = self.snapshot()
            resolved, info = resolve_selector(selector, current.get("elements", []))
            selector_info = dict(info)
            if resolved is None:
                return {
                    "status": "error",
                    "details": f"selector not found: {selector}",
                    "error_code": "selector_drift",
                    "selector": selector,
                    "selector_info": selector_info,
                    "command": command,
                }
            selector_info["resolved_ref"] = resolved.get("ref")

        if command is None:
            # Assertion actions are handled in verify() and don't dispatch a command.
            if op in {"assert_visible", "assert_eventually", "expect_transition"}:
                return {"status": "ok", "details": "assertion action uses verification loop", "command": None}
            return {"status": "error", "details": f"unsupported action: {op}", "command": None}

        result = self._run_or_record(command)
        self._apply_state_transition(action)
        self._last_action = op

        if selector_info:
            result["selector_info"] = selector_info
        return result

    def verify(self, assertion: dict[str, Any]) -> dict[str, Any]:
        selector = assertion.get("selector")
        timeout_ms = int(assertion.get("timeout_ms", assertion.get("timeout", 0) * 1000 or 5000))
        poll_ms = int(assertion.get("poll_ms", 250))
        elapsed = 0

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
                expected = assertion.get("value", assertion.get("target", selector.get("value") if selector else ""))
                actual = target.get("text") or target.get("label") or target.get("id")
                return {
                    "status": "ok",
                    "verdict": "pass",
                    "expected": expected,
                    "actual": actual,
                    "selector": selector,
                    "selector_info": selector_info,
                    "snapshot_tree_hash": snapshot.get("tree_hash"),
                }

            if elapsed >= timeout_ms:
                return {
                    "status": "fail",
                    "verdict": "fail",
                    "error_code": "assertion_timeout",
                    "details": "assertion condition was not met before timeout",
                    "selector": selector,
                    "elapsed_ms": elapsed,
                }

            sleep_seconds = poll_ms / 1000.0
            subprocess.run(f"sleep {sleep_seconds}", shell=True, check=False)
            elapsed += poll_ms

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
        root = {
            "id": "root",
            "label": self.app_identity(),
            "type": "root",
            "text": "",
            "path": "0",
            "ordinal": 0,
            "interactive": False,
        }
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
            }
            node["ref"] = build_ref(self.platform, node)
            node["anchor"] = build_anchor(node)
            nodes.append(node)
        return nodes

    @staticmethod
    def _tree_hash(elements: list[dict[str, Any]]) -> str:
        material = "|".join(
            [
                f"{el.get('ref')}:{el.get('id')}:{el.get('text')}:{el.get('path')}"
                for el in sorted(elements, key=lambda item: str(item.get("path", "")))
            ]
        )
        return build_ref("tree", {"id": material, "label": "", "type": "", "path": "", "ordinal": 0})
