#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from harness.driver.android import AndroidDriver
from harness.driver.ios import IOSDriver
from harness.driver.selectors import make_selector

LIGHTWEIGHT_SNAPSHOT_OPTIONS = (True, True)


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


_LIST_FIELDS = (
    "id",
    "label",
    "ref",
    "resource_id",
    "text",
    "content_desc",
    "class_name",
    "type",
    "interactive",
    "enabled",
    "visible",
    "bounds",
    "path",
)


def _compact_elements(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    elements = snapshot.get("elements", [])
    if not isinstance(elements, list):
        return []
    compact: list[dict[str, Any]] = []
    for element in elements:
        if isinstance(element, dict):
            compact.append({field: element.get(field) for field in _LIST_FIELDS})
    return compact


def _resolve_snapshot_options(
    interactive: bool | None = None,
    compact: bool | None = None,
) -> tuple[bool, bool]:
    default_interactive, default_compact = LIGHTWEIGHT_SNAPSHOT_OPTIONS
    return (
        default_interactive if interactive is None else interactive,
        default_compact if compact is None else compact,
    )


def _cached_snapshot(
    session: dict[str, Any],
    driver: AndroidDriver | IOSDriver,
    *,
    refresh: bool = False,
    interactive: bool | None = None,
    compact: bool | None = None,
) -> tuple[dict[str, Any], bool]:
    options = _resolve_snapshot_options(interactive=interactive, compact=compact)
    cache = session.setdefault("snapshot_cache", {})
    if not isinstance(cache, dict):
        cache = {}
        session["snapshot_cache"] = cache
    cache_key = f"{int(options[0])}:{int(options[1])}"
    if not refresh:
        cached = cache.get(cache_key)
        if isinstance(cached, dict):
            return cached, True
    snapshot = driver.snapshot({"interactive_only": options[0], "compact": options[1]})
    if isinstance(snapshot, dict):
        cache[cache_key] = snapshot
    return snapshot, False


def _invalidate_snapshot_cache(session: dict[str, Any]) -> None:
    session["snapshot_cache"] = {}


def _cached_elements(session: dict[str, Any]) -> list[dict[str, Any]] | None:
    cache = session.get("snapshot_cache")
    if not isinstance(cache, dict):
        return None
    for cache_key in ("1:1", "0:1", "1:0", "0:0"):
        snapshot = cache.get(cache_key)
        if not isinstance(snapshot, dict):
            continue
        maybe_elements = snapshot.get("elements", [])
        if isinstance(maybe_elements, list):
            return maybe_elements
    return None


def _score_text_match(query: str, value: str, *, exact: bool) -> int:
    if not value:
        return 0
    q = query.strip().lower()
    v = value.strip().lower()
    if not q or not v:
        return 0
    if v == q:
        return 4
    if exact:
        return 0
    if q in v:
        return 2
    return 0


def _find_elements(
    elements: list[dict[str, Any]],
    query: str,
    *,
    field: str = "any",
    exact: bool = False,
    limit: int = 20,
) -> list[dict[str, Any]]:
    search_fields = ("id", "label", "text", "content_desc", "resource_id", "ref", "class_name", "type")
    if field != "any":
        if field not in search_fields:
            raise SystemExit(f"unsupported field: {field}")
        selected_fields = (field,)
    else:
        selected_fields = search_fields

    results: list[dict[str, Any]] = []
    for element in elements:
        if not isinstance(element, dict):
            continue
        best_score = 0
        best_field = ""
        for candidate_field in selected_fields:
            score = _score_text_match(query, str(element.get(candidate_field, "")), exact=exact)
            if score > best_score:
                best_score = score
                best_field = candidate_field
        if best_score <= 0:
            continue
        row = {field_name: element.get(field_name) for field_name in _LIST_FIELDS}
        row["match_field"] = best_field
        row["match_score"] = best_score
        results.append(row)

    results.sort(
        key=lambda item: (
            -int(item.get("match_score", 0)),
            str(item.get("path", "")),
            str(item.get("ref", "")),
        )
    )
    return results[: max(1, limit)]


def _selector_from_value(value: str, platform: str) -> dict[str, Any]:
    if value.startswith("@e"):
        return make_selector(by="ref", value=value, platform_hint=platform)
    return make_selector(by="id", value=value, platform_hint=platform)


def _retry_android_preflight(
    driver: AndroidDriver | IOSDriver,
    *,
    timeout_ms: int = 6000,
    poll_ms: int = 500,
) -> dict[str, Any]:
    started = time.monotonic()
    last = driver.preflight()
    while (
        isinstance(driver, AndroidDriver)
        and last.get("status") in {"error", "fail"}
        and int((time.monotonic() - started) * 1000) < timeout_ms
    ):
        time.sleep(max(poll_ms, 0) / 1000.0)
        last = driver.preflight()
    return last


def cmd_open(args: argparse.Namespace) -> None:
    dispatch_commands = os.getenv("DISPATCH_COMMANDS", "0") == "1"
    if args.platform == "android":
        app = {"android_package": args.app}
        driver = AndroidDriver(app=app, dispatch_commands=dispatch_commands)
    else:
        app = {"ios_bundle_id": args.app}
        driver = IOSDriver(app=app, dispatch_commands=dispatch_commands)

    launch = driver.interact({"action": "launch_app"})
    preflight = _retry_android_preflight(driver)
    session = {
        "platform": args.platform,
        "app": app,
        "dispatch_commands": dispatch_commands,
        "state": driver.dump_state(),
        "snapshot_cache": {},
    }
    _save_session(Path(args.session_file), session)
    launch_failed = launch.get("status") in {"error", "fail"}
    if (
        args.platform == "android"
        and launch.get("command")
        and "monkey -p" in str(launch.get("command"))
        and int(launch.get("returncode", -1)) == 251
        and preflight.get("status") == "ok"
    ):
        launch_failed = False
        launch["status"] = "ok"
        launch["details"] = "monkey returned 251 but app launch verified by bridge preflight"
    status = "ok"
    if launch_failed or preflight.get("status") in {"error", "fail"}:
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
    interactive, compact = _resolve_snapshot_options(interactive=args.interactive, compact=args.compact)
    snapshot, cache_hit = _cached_snapshot(
        session,
        driver,
        refresh=bool(getattr(args, "refresh", False)),
        interactive=interactive,
        compact=compact,
    )
    session["state"] = driver.dump_state()
    _save_session(Path(args.session_file), session)
    print(json.dumps({"cache_hit": cache_hit, "snapshot": snapshot}, indent=2, ensure_ascii=True))


def cmd_list(args: argparse.Namespace) -> None:
    session = _load_session(Path(args.session_file))
    if not session:
        raise SystemExit(f"session not found: {args.session_file}")
    driver = _build_driver(session)
    snapshot, cache_hit = _cached_snapshot(
        session,
        driver,
        refresh=bool(getattr(args, "refresh", False)),
        interactive=True,
        compact=True,
    )
    session["state"] = driver.dump_state()
    _save_session(Path(args.session_file), session)
    elements = _compact_elements(snapshot)
    print(json.dumps({"cache_hit": cache_hit, "elements": elements}, indent=2, ensure_ascii=True))


def cmd_find(args: argparse.Namespace) -> None:
    session = _load_session(Path(args.session_file))
    if not session:
        raise SystemExit(f"session not found: {args.session_file}")
    driver = _build_driver(session)
    snapshot, cache_hit = _cached_snapshot(
        session,
        driver,
        refresh=bool(getattr(args, "refresh", False)),
        interactive=True,
        compact=True,
    )
    elements = snapshot.get("elements", [])
    if not isinstance(elements, list):
        elements = []
    matches = _find_elements(
        elements,
        args.query,
        field=args.field,
        exact=bool(args.exact),
        limit=int(args.limit),
    )
    session["state"] = driver.dump_state()
    _save_session(Path(args.session_file), session)
    print(json.dumps({"cache_hit": cache_hit, "matches": matches}, indent=2, ensure_ascii=True))


def cmd_press(args: argparse.Namespace) -> None:
    session = _load_session(Path(args.session_file))
    if not session:
        raise SystemExit(f"session not found: {args.session_file}")
    driver = _build_driver(session)
    selector = _selector_from_value(args.element, session["platform"])
    cached_elements = _cached_elements(session)
    result = driver.interact({"action": "tap", "selector": selector}, elements=cached_elements)
    if result.get("status") not in {"error", "fail"}:
        _invalidate_snapshot_cache(session)
    session["state"] = driver.dump_state()
    _save_session(Path(args.session_file), session)
    print(json.dumps({"status": "ok", "operation": "press", "result": result}, indent=2, ensure_ascii=True))


def cmd_fill(args: argparse.Namespace) -> None:
    session = _load_session(Path(args.session_file))
    if not session:
        raise SystemExit(f"session not found: {args.session_file}")
    driver = _build_driver(session)
    selector = _selector_from_value(args.element, session["platform"])
    cached_elements = _cached_elements(session)
    result = driver.interact({"action": "input_text", "selector": selector, "text": args.text}, elements=cached_elements)
    if result.get("status") not in {"error", "fail"}:
        _invalidate_snapshot_cache(session)
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
    snapshot_parser.add_argument("-i", "--interactive", action=argparse.BooleanOptionalAction, default=None)
    snapshot_parser.add_argument("-c", "--compact", action=argparse.BooleanOptionalAction, default=None)
    snapshot_parser.add_argument("--refresh", action="store_true")
    snapshot_parser.set_defaults(func=cmd_snapshot)

    list_parser = sub.add_parser("list", help="List selector-friendly elements from snapshot.")
    list_parser.add_argument("--refresh", action="store_true")
    list_parser.set_defaults(func=cmd_list)

    find_parser = sub.add_parser("find", help="Find likely elements by query.")
    find_parser.add_argument("query")
    find_parser.add_argument("--field", default="any")
    find_parser.add_argument("--exact", action="store_true")
    find_parser.add_argument("--limit", type=int, default=20)
    find_parser.add_argument("--refresh", action="store_true")
    find_parser.set_defaults(func=cmd_find)

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
