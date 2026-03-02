from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SUPPORTED_ACTIONS = {
    "launch_app",
    "tap",
    "input_text",
    "swipe",
    "wait",
    "assert_visible",
    "assert_eventually",
    "expect_transition",
}


@dataclass(frozen=True)
class Scenario:
    name: str
    platform: str
    app: dict[str, Any]
    steps: list[dict[str, Any]]
    dsl_version: str = "1.0"


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
        if step["action"] not in SUPPORTED_ACTIONS:
            raise ValueError(f"step {idx} has unsupported action: {step['action']}")

    return Scenario(
        name=raw["name"],
        platform=raw["platform"],
        app=raw["app"],
        steps=raw["steps"],
        dsl_version=str(raw.get("dsl_version", "1.0")),
    )
