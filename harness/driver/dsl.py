from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ASSERTION_ACTIONS = {"assert_visible", "assert_eventually", "expect_transition"}

SUPPORTED_ACTIONS = {
    "launch_app",
    "tap",
    "input_text",
    "swipe",
    "wait",
    *ASSERTION_ACTIONS,
}


@dataclass(frozen=True)
class Scenario:
    name: str
    platform: str
    app: dict[str, Any]
    steps: list[dict[str, Any]]
    dsl_version: str = "1.0"


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _has_target(step: dict[str, Any]) -> bool:
    return "target" in step and step["target"] is not None


def _validate_selector(step: dict[str, Any], idx: int, action: str) -> bool:
    if "selector" not in step:
        return False
    selector = step["selector"]
    if not isinstance(selector, dict) or "by" not in selector or "value" not in selector:
        raise ValueError(f"step {idx} {action} selector must be a dict with 'by' and 'value'")
    return True


def _validate_selector_or_target(step: dict[str, Any], idx: int, action: str) -> None:
    has_selector = _validate_selector(step, idx, action)
    has_target = _has_target(step)
    if not (has_selector or has_target):
        raise ValueError(f"step {idx} {action} requires selector (dict with 'by' and 'value') or target")


def _validate_tap(step: dict[str, Any], idx: int) -> None:
    has_selector = _validate_selector(step, idx, "tap")
    has_target = _has_target(step)
    x_present = "x" in step
    y_present = "y" in step
    if x_present or y_present:
        if not (_is_int(step.get("x")) and _is_int(step.get("y"))):
            raise ValueError(f"step {idx} tap requires integer x and y coordinates when provided")
        has_coordinates = True
    else:
        has_coordinates = False

    if not (has_selector or has_target or has_coordinates):
        raise ValueError(
            f"step {idx} tap requires selector (dict with 'by' and 'value'), target, or integer x/y coordinates"
        )


def load_scenario(path: str | Path) -> Scenario:
    scenario_path = Path(path)
    raw = json.loads(scenario_path.read_text(encoding="utf-8"))

    for key in ("name", "platform", "app", "steps"):
        if key not in raw:
            raise ValueError(f"scenario missing required key: {key}")

    if not isinstance(raw["steps"], list) or not raw["steps"]:
        raise ValueError("scenario steps must be a non-empty list")

    for idx, step in enumerate(raw["steps"]):
        if "action" not in step:
            raise ValueError(f"step {idx} missing action")
        action = step["action"]
        if action not in SUPPORTED_ACTIONS:
            raise ValueError(f"step {idx} has unsupported action: {action}")
        if action == "tap":
            _validate_tap(step, idx)
        elif action == "input_text":
            _validate_selector_or_target(step, idx, action)
        elif action in ASSERTION_ACTIONS:
            _validate_selector_or_target(step, idx, action)

    return Scenario(
        name=raw["name"],
        platform=raw["platform"],
        app=raw["app"],
        steps=raw["steps"],
        dsl_version=str(raw.get("dsl_version", "1.0")),
    )
