#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from harness.driver.android import AndroidDriver
from harness.driver.ios import IOSDriver
from harness.driver.selectors import make_selector


def _load_session(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _save_session(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=True), encoding="utf-8")


def _build_driver(session: dict[str, Any]) -> AndroidDriver | IOSDriver:
    platform = session["platform"]
    app = session["app"]
    dispatch_commands = bool(session.get("dispatch_commands", False))
    if platform == "android":
        driver = AndroidDriver(app=app, dispatch_commands=dispatch_commands)
    elif platform == "ios":
        driver = IOSDriver(app=app, dispatch_commands=dispatch_commands)
    else:
        raise SystemExit(f"unsupported platform: {platform}")
    driver.restore_state(session.get("state", {}))
    return driver


_LIST_FIELDS = ("id", "label", "ref", "resource_id", "text", "bounds", "path")


def _compact_elements(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    elements = snapshot.get("elements", [])
    if not isinstance(elements, list):
        return []
    compact: list[dict[str, Any]] = []
    for element in elements:
        if isinstance(element, dict):
            compact.append({field: element.get(field) for field in _LIST_FIELDS})
    return compact


def _selector_from_value(value: str, platform: str) -> dict[str, Any]:
    if value.startswith("@e"):
        return make_selector(by="ref", value=value, platform_hint=platform)
    return make_selector(by="id", value=value, platform_hint=platform)


def cmd_open(args: argparse.Namespace) -> None:
    dispatch_commands = os.getenv("DISPATCH_COMMANDS", "0") == "1"
    if args.platform == "android":
        app = {"android_package": args.app}
        driver = AndroidDriver(app=app, dispatch_commands=dispatch_commands)
    else:
        app = {"ios_bundle_id": args.app}
        driver = IOSDriver(app=app, dispatch_commands=dispatch_commands)

    launch = driver.interact({"action": "launch_app"})
    preflight = driver.preflight()
    session = {
        "platform": args.platform,
        "app": app,
        "dispatch_commands": dispatch_commands,
        "state": driver.dump_state(),
    }
    _save_session(Path(args.session_file), session)
    status = "ok"
    if launch.get("status") in {"error", "fail"} or preflight.get("status") in {"error", "fail"}:
        status = "error"
    print(
        json.dumps(
            {
                "status": status,
                "operation": "open",
                "result": {"launch": launch, "preflight": preflight},
            },
            indent=2,
            ensure_ascii=True,
        )
    )


def cmd_snapshot(args: argparse.Namespace) -> None:
    session = _load_session(Path(args.session_file))
    if not session:
        raise SystemExit(f"session not found: {args.session_file}")
    driver = _build_driver(session)
    snapshot = driver.snapshot({"interactive_only": args.interactive, "compact": args.compact})
    session["state"] = driver.dump_state()
    _save_session(Path(args.session_file), session)
    print(json.dumps(snapshot, indent=2, ensure_ascii=True))


def cmd_list(args: argparse.Namespace) -> None:
    session = _load_session(Path(args.session_file))
    if not session:
        raise SystemExit(f"session not found: {args.session_file}")
    driver = _build_driver(session)
    snapshot = driver.snapshot({"interactive_only": True, "compact": True})
    session["state"] = driver.dump_state()
    _save_session(Path(args.session_file), session)
    elements = _compact_elements(snapshot)
    print(json.dumps(elements, indent=2, ensure_ascii=True))


def cmd_press(args: argparse.Namespace) -> None:
    session = _load_session(Path(args.session_file))
    if not session:
        raise SystemExit(f"session not found: {args.session_file}")
    driver = _build_driver(session)
    selector = _selector_from_value(args.element, session["platform"])
    result = driver.interact({"action": "tap", "selector": selector})
    session["state"] = driver.dump_state()
    _save_session(Path(args.session_file), session)
    print(json.dumps({"status": "ok", "operation": "press", "result": result}, indent=2, ensure_ascii=True))


def cmd_fill(args: argparse.Namespace) -> None:
    session = _load_session(Path(args.session_file))
    if not session:
        raise SystemExit(f"session not found: {args.session_file}")
    driver = _build_driver(session)
    selector = _selector_from_value(args.element, session["platform"])
    result = driver.interact({"action": "input_text", "selector": selector, "text": args.text})
    session["state"] = driver.dump_state()
    _save_session(Path(args.session_file), session)
    print(json.dumps({"status": "ok", "operation": "fill", "result": result}, indent=2, ensure_ascii=True))


def cmd_verify(args: argparse.Namespace) -> None:
    session = _load_session(Path(args.session_file))
    if not session:
        raise SystemExit(f"session not found: {args.session_file}")
    driver = _build_driver(session)
    selector = _selector_from_value(args.element, session["platform"])
    assertion = {
        "action": "assert_visible",
        "selector": selector,
        "timeout_ms": args.timeout_ms,
        "value": args.expected,
    }
    result = driver.verify(assertion)
    session["state"] = driver.dump_state()
    _save_session(Path(args.session_file), session)
    print(json.dumps({"status": "ok", "operation": "verify", "result": result}, indent=2, ensure_ascii=True))


def main() -> None:
    parser = argparse.ArgumentParser(description="Unified mobile harness CLI for iOS and Android.")
    parser.add_argument("--session-file", default=".device_harness_session.json")
    sub = parser.add_subparsers(dest="cmd", required=True)

    open_parser = sub.add_parser("open", help="Boot and launch an app in the selected platform harness.")
    open_parser.add_argument("--platform", choices=["android", "ios"], required=True)
    open_parser.add_argument("app", help="Android package or iOS bundle id")
    open_parser.set_defaults(func=cmd_open)

    snapshot_parser = sub.add_parser("snapshot", help="Capture a compact accessibility tree.")
    snapshot_parser.add_argument("-i", "--interactive", action="store_true")
    snapshot_parser.add_argument("-c", "--compact", action="store_true")
    snapshot_parser.set_defaults(func=cmd_snapshot)

    list_parser = sub.add_parser("list", help="List selector-friendly elements from snapshot.")
    list_parser.set_defaults(func=cmd_list)

    press_parser = sub.add_parser("press", help="Tap a referenced element.")
    press_parser.add_argument("element", help="@e ref or element id")
    press_parser.set_defaults(func=cmd_press)

    fill_parser = sub.add_parser("fill", help="Input text into a referenced element.")
    fill_parser.add_argument("element", help="@e ref or element id")
    fill_parser.add_argument("text")
    fill_parser.set_defaults(func=cmd_fill)

    verify_parser = sub.add_parser("verify", help="Verify an element is visible within timeout.")
    verify_parser.add_argument("element", help="@e ref or element id")
    verify_parser.add_argument("expected")
    verify_parser.add_argument("--timeout-ms", type=int, default=5000)
    verify_parser.set_defaults(func=cmd_verify)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
