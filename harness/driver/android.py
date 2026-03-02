from __future__ import annotations

import shlex
from typing import Any

from harness.driver.device_bridge import DeviceHarness


class AndroidDriver(DeviceHarness):
    def __init__(self, app: dict[str, Any], dispatch_commands: bool = False) -> None:
        super().__init__(platform="android", app=app, dispatch_commands=dispatch_commands)

    def app_identity(self) -> str:
        return str(self.app.get("android_package", "android.app"))

    def command_for_action(self, action: dict[str, Any]) -> str | None:
        op = action.get("action")
        package = str(self.app.get("android_package", ""))

        if op == "launch_app":
            return f"adb shell monkey -p {shlex.quote(package)} -c android.intent.category.LAUNCHER 1"

        if op == "tap":
            if "x" in action and "y" in action:
                return f"adb shell input tap {int(action['x'])} {int(action['y'])}"
            return "adb shell input tap 100 200"

        if op == "input_text":
            text = shlex.quote(str(action.get("text", "")))
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
