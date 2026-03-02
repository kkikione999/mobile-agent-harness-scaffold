from __future__ import annotations

import shlex
from typing import Any

from harness.driver.device_bridge import DeviceHarness


class IOSDriver(DeviceHarness):
    def __init__(self, app: dict[str, Any], dispatch_commands: bool = False) -> None:
        super().__init__(platform="ios", app=app, dispatch_commands=dispatch_commands)

    def app_identity(self) -> str:
        return str(self.app.get("ios_bundle_id", "ios.app"))

    def command_for_action(self, action: dict[str, Any]) -> str | None:
        op = action.get("action")
        bundle_id = str(self.app.get("ios_bundle_id", ""))
        simulator = str(action.get("simulator", "booted"))

        if op == "launch_app":
            return f"xcrun simctl launch {shlex.quote(simulator)} {shlex.quote(bundle_id)}"

        if op == "tap":
            if "x" in action and "y" in action:
                return f"xcrun simctl io booted tap {int(action['x'])} {int(action['y'])}"
            # Placeholder command that preserves deterministic traces without requiring XCTest bridge.
            return "xcrun simctl getenv booted SIMULATOR_UDID"

        if op == "input_text":
            text = shlex.quote(str(action.get("text", "")))
            return f"xcrun simctl io booted keyboard text {text}"

        if op == "swipe":
            return "xcrun simctl getenv booted SIMULATOR_UDID"

        if op == "wait":
            return f"sleep {float(action.get('seconds', 1))}"

        if op in {"assert_visible", "assert_eventually", "expect_transition"}:
            return None

        return None
