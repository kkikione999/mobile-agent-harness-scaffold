#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

PROTOCOL_VERSION = "2024-11-05"
SERVER_INFO = {"name": "mobile-agent-harness-mcp", "version": "0.1.0"}


@dataclass
class CommandResult:
    returncode: int
    stdout: str
    stderr: str


Runner = Callable[[list[str], Optional[dict[str, str]]], CommandResult]
DEFAULT_SESSION_FILE = ".device_harness_session.json"
LIGHTWEIGHT_SNAPSHOT_OPTIONS = (True, True)
SnapshotOptions = tuple[bool, bool]
FULL_SNAPSHOT_OPTIONS = (False, False)
SETTLEMENT_TIMEOUT_MS = 1000
SETTLEMENT_POLL_MS = 100
SETTLEMENT_STABLE_OBSERVATIONS = 2


@dataclass
class DeviceSession:
    platform: str
    app: dict[str, Any]
    dispatch_commands: bool
    driver: Any
    snapshot_cache: dict[SnapshotOptions, dict[str, Any]] = field(default_factory=dict)


DEVICE_SESSION_CACHE: dict[str, DeviceSession] = {}


def _run_command(command: list[str], env_overrides: dict[str, str] | None = None) -> CommandResult:
    env = dict(os.environ)
    if env_overrides:
        env.update(env_overrides)
    proc = subprocess.run(command, capture_output=True, text=True, check=False, cwd=REPO_ROOT, env=env)
    return CommandResult(returncode=proc.returncode, stdout=proc.stdout, stderr=proc.stderr)


def _line_after_prefix(text: str, prefix: str) -> str | None:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith(prefix):
            return stripped.replace(prefix, "", 1).strip()
    return None


def _maybe_json(text: str) -> Any | None:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def _expect_str(arguments: dict[str, Any], key: str) -> str:
    value = arguments.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"'{key}' must be a non-empty string")
    return value


def _optional_str(arguments: dict[str, Any], key: str) -> str | None:
    value = arguments.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise ValueError(f"'{key}' must be a non-empty string when provided")
    return value


def _optional_bool(arguments: dict[str, Any], key: str) -> bool | None:
    value = arguments.get(key)
    if value is None:
        return None
    if not isinstance(value, bool):
        raise ValueError(f"'{key}' must be a boolean")
    return value


def _optional_int(arguments: dict[str, Any], key: str) -> int | None:
    value = arguments.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"'{key}' must be an integer")
    return value


def _execute_script(
    script_name: str,
    script_args: list[str],
    runner: Runner,
    env_overrides: dict[str, str] | None = None,
) -> tuple[CommandResult, dict[str, Any]]:
    command = [sys.executable, str(REPO_ROOT / "tools" / script_name), *script_args]
    result = runner(command, env_overrides)
    payload = {
        "command": command,
        "env_overrides": env_overrides or {},
        "exit_code": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }
    return result, payload


def _tool_run_scenario(arguments: dict[str, Any], runner: Runner) -> tuple[bool, dict[str, Any]]:
    scenario = _expect_str(arguments, "scenario")
    platform = _expect_str(arguments, "platform")
    run_root = _optional_str(arguments, "run_root")
    dispatch_commands = _optional_bool(arguments, "dispatch_commands")

    args = ["--scenario", scenario, "--platform", platform]
    if run_root:
        args.extend(["--run-root", run_root])

    env_overrides = None
    if dispatch_commands is not None:
        env_overrides = {"DISPATCH_COMMANDS": "1" if dispatch_commands else "0"}

    result, payload = _execute_script("run_scenario.py", args, runner, env_overrides=env_overrides)
    payload["run_dir"] = _line_after_prefix(result.stdout, "run complete: ")
    return result.returncode != 0, payload


def _tool_evaluate_run(arguments: dict[str, Any], runner: Runner) -> tuple[bool, dict[str, Any]]:
    run_dir = _expect_str(arguments, "run_dir")
    rules = _optional_str(arguments, "rules")

    args = ["--run-dir", run_dir]
    if rules:
        args.extend(["--rules", rules])

    result, payload = _execute_script("evaluate_run.py", args, runner)
    payload["oracle_result"] = _line_after_prefix(result.stdout, "oracle result: ")
    payload["report_path"] = _line_after_prefix(result.stdout, "report: ")
    return result.returncode != 0, payload


def _tool_package_failure(arguments: dict[str, Any], runner: Runner) -> tuple[bool, dict[str, Any]]:
    run_dir = _expect_str(arguments, "run_dir")
    result, payload = _execute_script("package_failure.py", ["--run-dir", run_dir], runner)
    payload["bundle_path"] = _line_after_prefix(result.stdout, "bundle: ")
    return result.returncode != 0, payload


def _tool_replay_run(arguments: dict[str, Any], runner: Runner) -> tuple[bool, dict[str, Any]]:
    run_dir = _expect_str(arguments, "run_dir")
    mode = _optional_str(arguments, "mode")
    run_root = _optional_str(arguments, "run_root")

    args = ["--run-dir", run_dir]
    if mode:
        args.extend(["--mode", mode])
    if run_root:
        args.extend(["--run-root", run_root])

    result, payload = _execute_script("replay_run.py", args, runner)
    payload["replay_report_path"] = _line_after_prefix(result.stdout, "replay report: ")
    payload["structural_consistency_score"] = _line_after_prefix(result.stdout, "structural consistency score: ")
    return result.returncode != 0, payload


def _tool_query_telemetry(arguments: dict[str, Any], runner: Runner) -> tuple[bool, dict[str, Any]]:
    query = _expect_str(arguments, "query")
    run_root = _optional_str(arguments, "run_root")
    limit = _optional_int(arguments, "limit")

    args = ["--query", query]
    if run_root:
        args.extend(["--run-root", run_root])
    if limit is not None:
        args.extend(["--limit", str(limit)])

    result, payload = _execute_script("query_telemetry.py", args, runner)
    payload["query_result"] = _maybe_json(result.stdout)
    return result.returncode != 0, payload


def _tool_update_selectors(arguments: dict[str, Any], runner: Runner) -> tuple[bool, dict[str, Any]]:
    run_dir = _expect_str(arguments, "run_dir")
    session = _optional_str(arguments, "session")
    output = _optional_str(arguments, "output")

    args = ["--run-dir", run_dir]
    if session:
        args.extend(["--session", session])
    if output:
        args.extend(["--output", output])

    result, payload = _execute_script("update_selectors.py", args, runner)
    payload["updated_session_path"] = _line_after_prefix(result.stdout, "updated session: ")
    payload["selector_report_path"] = _line_after_prefix(result.stdout, "selector report: ")
    return result.returncode != 0, payload


def _normalize_session_path(session_file: str | None) -> Path:
    candidate = Path(session_file) if session_file else Path(DEFAULT_SESSION_FILE)
    candidate = candidate.expanduser()
    if not candidate.is_absolute():
        candidate = (REPO_ROOT / candidate).resolve()
    return candidate


def _build_device_driver(platform: str, app: dict[str, Any], dispatch_commands: bool) -> Any:
    if platform == "android":
        from harness.driver.android import AndroidDriver

        return AndroidDriver(app=app, dispatch_commands=dispatch_commands)
    if platform == "ios":
        from harness.driver.ios import IOSDriver

        return IOSDriver(app=app, dispatch_commands=dispatch_commands)
    raise ValueError(f"unsupported platform: {platform}")


def _selector_from_value(value: str, platform: str) -> dict[str, Any]:
    from harness.driver.selectors import make_selector

    if value.startswith("@e"):
        by = "ref"
    elif _looks_like_semantic_id(value):
        by = "semantic_id"
    else:
        by = "id"
    return make_selector(by=by, value=value, platform_hint=platform)


SEMANTIC_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)+$")


def _looks_like_semantic_id(value: str) -> bool:
    return bool(SEMANTIC_ID_PATTERN.fullmatch(value.strip()))


def _selector_from_payload(value: Any, platform: str) -> dict[str, Any]:
    from harness.driver.selectors import make_selector

    if not isinstance(value, dict):
        raise ValueError("'selector' must be an object")
    by = value.get("by")
    target_value = value.get("value")
    if not isinstance(by, str) or not by:
        raise ValueError("'selector.by' must be a non-empty string")
    if not isinstance(target_value, str) or not target_value:
        raise ValueError("'selector.value' must be a non-empty string")

    within = value.get("within")
    if within is not None and (not isinstance(within, str) or not within):
        raise ValueError("'selector.within' must be a non-empty string when provided")
    anchor = value.get("anchor")
    if anchor is not None and not isinstance(anchor, dict):
        raise ValueError("'selector.anchor' must be an object when provided")
    ambiguity_mode = value.get("ambiguity_mode")
    if ambiguity_mode is not None and ambiguity_mode not in {"first", "error"}:
        raise ValueError("'selector.ambiguity_mode' must be 'first' or 'error'")
    candidate_limit = value.get("candidate_limit")
    if candidate_limit is not None:
        if isinstance(candidate_limit, bool) or not isinstance(candidate_limit, int):
            raise ValueError("'selector.candidate_limit' must be an integer when provided")
        if candidate_limit <= 0:
            raise ValueError("'selector.candidate_limit' must be greater than 0")

    selector = make_selector(
        by=by,
        value=target_value,
        within=within,
        platform_hint=platform,
    )
    if anchor is not None:
        selector["anchor"] = anchor
    if ambiguity_mode is not None:
        selector["ambiguity_mode"] = ambiguity_mode
    if candidate_limit is not None:
        selector["candidate_limit"] = candidate_limit
    return selector


def _selector_from_arguments(arguments: dict[str, Any], platform: str) -> tuple[dict[str, Any], bool]:
    selector_payload = arguments.get("selector")
    if selector_payload is not None:
        return _selector_from_payload(selector_payload, platform), True
    return _selector_from_value(_expect_str(arguments, "element"), platform), False


def _selector_options(arguments: dict[str, Any], *, selector_supplied: bool) -> tuple[str | None, int | None]:
    ambiguity_mode = _optional_str(arguments, "ambiguity_mode")
    if ambiguity_mode is not None and ambiguity_mode not in {"first", "error"}:
        raise ValueError("'ambiguity_mode' must be 'first' or 'error'")
    candidate_limit = _optional_int(arguments, "candidate_limit")
    if candidate_limit is not None and candidate_limit <= 0:
        raise ValueError("'candidate_limit' must be greater than 0")

    if ambiguity_mode is None and selector_supplied:
        ambiguity_mode = "error"
    return ambiguity_mode, candidate_limit


_LIST_FIELDS = (
    "id",
    "screen_id",
    "semantic_id",
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


def _snapshot_elements(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    elements = snapshot.get("elements", [])
    if not isinstance(elements, list):
        return []
    return [element for element in elements if isinstance(element, dict)]


def _path_depth(path: Any) -> int:
    text = str(path).strip()
    if not text:
        return 9999
    return text.count("/")


def _snapshot_root_ref(snapshot: dict[str, Any]) -> str | None:
    root_ref = snapshot.get("root")
    if isinstance(root_ref, str) and root_ref.strip():
        return root_ref.strip()
    return None


def _snapshot_screen_id(snapshot: dict[str, Any]) -> str | None:
    screen_id = snapshot.get("screen_id")
    if isinstance(screen_id, str) and screen_id:
        return screen_id
    for element in _snapshot_elements(snapshot):
        candidate = element.get("screen_id")
        if isinstance(candidate, str) and candidate:
            return candidate
    return None


def _choose_page_root(snapshot: dict[str, Any]) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    elements = _snapshot_elements(snapshot)
    if not elements:
        return None, {"strategy": "empty", "snapshot_root_ref": None, "ordered_root_ref": None}

    by_ref = {
        str(element.get("ref")): element
        for element in elements
        if isinstance(element.get("ref"), str) and str(element.get("ref")).strip()
    }
    snapshot_root_ref = _snapshot_root_ref(snapshot)
    ordered_root_ref = next(
        (str(element.get("ref")) for element in elements if isinstance(element.get("ref"), str) and str(element.get("ref")).strip()),
        None,
    )
    if snapshot_root_ref and snapshot_root_ref in by_ref:
        return by_ref[snapshot_root_ref], {
            "strategy": "snapshot_root",
            "snapshot_root_ref": snapshot_root_ref,
            "ordered_root_ref": ordered_root_ref,
        }

    screen_id = _snapshot_screen_id(snapshot)
    if screen_id:
        candidates = [element for element in elements if str(element.get("screen_id", "")) == screen_id]
        if candidates:
            candidates.sort(key=lambda item: (_path_depth(item.get("path")), str(item.get("path", "")), str(item.get("ref", ""))))
            return candidates[0], {
                "strategy": "screen_id_fallback",
                "snapshot_root_ref": snapshot_root_ref,
                "ordered_root_ref": ordered_root_ref,
            }

    path_root = next((element for element in elements if str(element.get("path", "")) == "0"), None)
    if path_root is not None:
        return path_root, {
            "strategy": "path_fallback",
            "snapshot_root_ref": snapshot_root_ref,
            "ordered_root_ref": ordered_root_ref,
        }

    return elements[0], {
        "strategy": "ordered_fallback",
        "snapshot_root_ref": snapshot_root_ref,
        "ordered_root_ref": ordered_root_ref,
    }


def _capture_source_is_degraded(capture_source: str) -> bool:
    normalized = capture_source.strip().lower()
    if not normalized or normalized == "unknown":
        return True
    return normalized.startswith("adb_") or "fallback" in normalized


def _snapshot_introspection(snapshot: dict[str, Any]) -> dict[str, Any]:
    elements = _snapshot_elements(snapshot)
    visible_elements = sum(1 for element in elements if bool(element.get("visible", True)))
    interactive_elements = sum(1 for element in elements if bool(element.get("interactive")))
    semantic_id_count = sum(
        1
        for element in elements
        if isinstance(element.get("semantic_id"), str) and str(element.get("semantic_id")).strip()
    )
    screen_ids = sorted(
        {
            str(element.get("screen_id"))
            for element in elements
            if isinstance(element.get("screen_id"), str) and str(element.get("screen_id")).strip()
        }
    )
    capture_source = snapshot.get("capture_source")
    if not isinstance(capture_source, str) or not capture_source:
        capture_source = "unknown"
    capture_error = snapshot.get("capture_error")
    if not isinstance(capture_error, dict):
        capture_error = None

    page_root, root_resolution = _choose_page_root(snapshot)
    screen_id = _snapshot_screen_id(snapshot)
    page_root_screen_id = page_root.get("screen_id") if isinstance(page_root, dict) else None
    snapshot_root_ref = _snapshot_root_ref(snapshot)
    consistency = {
        "snapshot_root_present": bool(snapshot_root_ref and root_resolution.get("strategy") == "snapshot_root"),
        "ordered_root_matches_snapshot_root": not snapshot_root_ref or snapshot_root_ref == root_resolution.get("ordered_root_ref"),
        "root_screen_matches_snapshot": not screen_id or not page_root_screen_id or screen_id == page_root_screen_id,
        "single_screen_id": len(screen_ids) <= 1,
        "root_resolution": root_resolution.get("strategy"),
    }

    degraded_reasons: list[str] = []
    if _capture_source_is_degraded(capture_source):
        degraded_reasons.append("capture_source_degraded")
    if capture_error is not None:
        error_code = capture_error.get("error_code")
        degraded_reasons.append(f"capture_error:{error_code or 'unknown'}")
    if not screen_id:
        degraded_reasons.append("missing_screen_id")
    if semantic_id_count <= 0:
        degraded_reasons.append("missing_semantic_ids")
    if snapshot_root_ref and root_resolution.get("strategy") != "snapshot_root":
        degraded_reasons.append("missing_snapshot_root")
    if not consistency["root_screen_matches_snapshot"]:
        degraded_reasons.append("inconsistent_root_screen_id")
    if not consistency["single_screen_id"]:
        degraded_reasons.append("multiple_screen_ids")

    return {
        "screen_id": screen_id,
        "root_ref": snapshot_root_ref,
        "capture_source": capture_source,
        "capture_error": capture_error,
        "total_elements": len(elements),
        "visible_elements": visible_elements,
        "interactive_elements": interactive_elements,
        "semantic_id_count": semantic_id_count,
        "screen_ids": screen_ids,
        "live_semantics_ready": not degraded_reasons,
        "degraded": bool(degraded_reasons),
        "degraded_reasons": degraded_reasons,
        "consistency": consistency,
    }


def _build_page_map(snapshot: dict[str, Any]) -> dict[str, Any]:
    snapshot_summary = _snapshot_introspection(snapshot)
    elements = _snapshot_elements(snapshot)
    root, root_resolution = _choose_page_root(snapshot)
    if not elements or root is None:
        return {
            "tree_hash": snapshot.get("tree_hash"),
            "snapshot": snapshot_summary,
            "page": {
                "screen_id": snapshot_summary.get("screen_id"),
                "root": None,
                "signature": {},
                "sections": [],
                "interactive_refs": [],
                "root_resolution": root_resolution,
            },
        }

    root_path = str(root.get("path", "0"))
    root_prefix = f"{root_path}/"
    sections: list[dict[str, Any]] = []

    for element in elements:
        if element is root:
            continue
        path = str(element.get("path", ""))
        if not path.startswith(root_prefix):
            continue
        relative = path[len(root_prefix):]
        if not relative or "/" in relative:
            continue
        child_prefix = f"{path}/"
        child_count = sum(
            1
            for candidate in elements
            if isinstance(candidate, dict) and str(candidate.get("path", "")).startswith(child_prefix)
        )
        sections.append(
            {
                "ref": element.get("ref"),
                "id": element.get("id"),
                "label": element.get("label"),
                "path": element.get("path"),
                "child_count": child_count,
                "interactive": bool(element.get("interactive")),
                "visible": bool(element.get("visible", True)),
            }
        )

    interactive_refs = [
        element.get("ref")
        for element in elements
        if isinstance(element, dict)
        and bool(element.get("interactive"))
        and bool(element.get("visible", True))
        and isinstance(element.get("ref"), str)
    ]

    root_summary = {
        field: root.get(field)
        for field in ("ref", "id", "screen_id", "semantic_id", "resource_id", "label", "text", "path")
    }
    signature = {
        field: root.get(field)
        for field in ("id", "screen_id", "semantic_id", "resource_id", "label", "text")
    }
    return {
        "tree_hash": snapshot.get("tree_hash"),
        "snapshot": snapshot_summary,
        "page": {
            "screen_id": snapshot_summary.get("screen_id"),
            "root": root_summary,
            "signature": signature,
            "sections": sections,
            "interactive_refs": interactive_refs,
            "root_resolution": root_resolution,
        },
    }


def _build_element_dictionary(
    snapshot: dict[str, Any],
    *,
    fields: list[str] | None = None,
) -> dict[str, Any]:
    snapshot_summary = _snapshot_introspection(snapshot)
    selected_fields = fields or ["screen_id", "semantic_id", "id", "resource_id", "label", "text", "content_desc"]
    allowed_fields = {"screen_id", "semantic_id", "id", "resource_id", "label", "text", "content_desc", "class_name", "type"}
    invalid = [field for field in selected_fields if field not in allowed_fields]
    if invalid:
        raise ValueError(f"unsupported dictionary fields: {', '.join(sorted(set(invalid)))}")

    elements = _snapshot_elements(snapshot)

    dictionary: dict[str, dict[str, Any]] = {field: {} for field in selected_fields}
    ambiguous: list[dict[str, Any]] = []
    field_stats: dict[str, dict[str, int]] = {}
    for field in selected_fields:
        grouped: dict[str, list[dict[str, Any]]] = {}
        for element in elements:
            raw_value = element.get(field)
            if raw_value is None:
                continue
            value = str(raw_value).strip()
            if not value:
                continue
            grouped.setdefault(value, []).append(element)

        for value, grouped_elements in sorted(grouped.items()):
            grouped_elements.sort(key=lambda item: (str(item.get("path", "")), str(item.get("ref", ""))))
            refs = [str(item.get("ref", "")) for item in grouped_elements if item.get("ref")]
            summary = {
                "count": len(grouped_elements),
                "refs": refs,
                "elements": [
                    {
                        key: item.get(key)
                        for key in (
                            "ref",
                            "id",
                            "screen_id",
                            "semantic_id",
                            "label",
                            "path",
                            "resource_id",
                            "text",
                            "content_desc",
                            "class_name",
                            "type",
                        )
                    }
                    for item in grouped_elements
                ],
            }
            dictionary[field][value] = summary
            if field != "screen_id" and len(grouped_elements) > 1:
                ambiguous.append({"field": field, "value": value, "count": len(grouped_elements), "refs": refs})
        field_stats[field] = {
            "value_count": len(grouped),
            "ambiguous_value_count": sum(
                1
                for grouped_elements in grouped.values()
                if field != "screen_id" and len(grouped_elements) > 1
            ),
        }

    return {
        "tree_hash": snapshot.get("tree_hash"),
        "snapshot": snapshot_summary,
        "dictionary": dictionary,
        "ambiguous": ambiguous,
        "summary": {
            "fields": selected_fields,
            "ambiguous_entry_count": len(ambiguous),
            "field_stats": field_stats,
            "recommended_lookup_fields": (
                ["semantic_id", "id", "resource_id", "label"]
                if bool(snapshot_summary.get("live_semantics_ready"))
                else ["screen_id", "id", "resource_id", "label", "text", "content_desc"]
            ),
        },
    }


def _resolve_snapshot_options(
    interactive: bool | None = None,
    compact: bool | None = None,
) -> SnapshotOptions:
    default_interactive, default_compact = LIGHTWEIGHT_SNAPSHOT_OPTIONS
    return (
        default_interactive if interactive is None else interactive,
        default_compact if compact is None else compact,
    )


def _cached_snapshot(
    session: DeviceSession,
    *,
    interactive: bool | None = None,
    compact: bool | None = None,
    refresh: bool = False,
) -> tuple[dict[str, Any], bool]:
    options = _resolve_snapshot_options(interactive=interactive, compact=compact)
    if not refresh:
        cached = session.snapshot_cache.get(options)
        if isinstance(cached, dict):
            return cached, True
        if options == LIGHTWEIGHT_SNAPSHOT_OPTIONS:
            full_cached = session.snapshot_cache.get(FULL_SNAPSHOT_OPTIONS)
            if isinstance(full_cached, dict):
                full_summary = _snapshot_introspection(full_cached)
                if bool(full_summary.get("live_semantics_ready")):
                    return full_cached, True
    snapshot = session.driver.snapshot({"interactive_only": options[0], "compact": options[1]})
    if isinstance(snapshot, dict):
        session.snapshot_cache[options] = snapshot
    return snapshot, False


def _invalidate_snapshot_cache(session: DeviceSession) -> None:
    session.snapshot_cache.clear()


def _cached_elements(session: DeviceSession) -> list[dict[str, Any]] | None:
    for options in (LIGHTWEIGHT_SNAPSHOT_OPTIONS, (False, True), (True, False), (False, False)):
        snapshot = session.snapshot_cache.get(options)
        if not isinstance(snapshot, dict):
            continue
        maybe_elements = snapshot.get("elements", [])
        if isinstance(maybe_elements, list):
            return maybe_elements
    return None


def _seed_snapshot_cache(session: DeviceSession, snapshot: dict[str, Any], options: SnapshotOptions = FULL_SNAPSHOT_OPTIONS) -> None:
    if isinstance(snapshot, dict):
        session.snapshot_cache[options] = snapshot


def _settlement_result(
    *,
    status: str,
    attempts: int,
    elapsed_ms: int,
    stable_observations: int,
    snapshot: dict[str, Any],
) -> dict[str, Any]:
    return {
        "status": status,
        "attempts": attempts,
        "elapsed_ms": elapsed_ms,
        "stable_observations": stable_observations,
        "tree_hash": snapshot.get("tree_hash"),
        "screen_id": snapshot.get("screen_id"),
        "root": snapshot.get("root"),
        "snapshot": snapshot,
    }


def _selector_retry_context(selector: dict[str, Any], snapshot: dict[str, Any]) -> dict[str, Any]:
    selector_value = selector.get("value")
    probe = selector_value.strip() if isinstance(selector_value, str) else ""
    elements = _snapshot_elements(snapshot)
    selector_presence = {
        "semantic_id": False,
        "id": False,
        "resource_id": False,
        "label": False,
        "text": False,
        "content_desc": False,
    }
    matching_screen_ids: set[str] = set()
    if probe:
        for element in elements:
            for field in selector_presence:
                value = element.get(field)
                if isinstance(value, str) and value == probe:
                    selector_presence[field] = True
                    screen_id = element.get("screen_id")
                    if isinstance(screen_id, str) and screen_id.strip():
                        matching_screen_ids.add(screen_id)

    snapshot_summary = _snapshot_introspection(snapshot)
    return {
        "attempted_full_snapshot": True,
        "selector_value": probe,
        "selector_presence": selector_presence,
        "matching_screen_ids": sorted(matching_screen_ids),
        "semantic_retry_preserved": bool(snapshot_summary.get("live_semantics_ready")),
        "full_snapshot": {
            "tree_hash": snapshot.get("tree_hash"),
            "screen_id": snapshot_summary.get("screen_id"),
            "screen_ids": snapshot_summary.get("screen_ids"),
            "capture_source": snapshot_summary.get("capture_source"),
            "semantic_id_count": snapshot_summary.get("semantic_id_count"),
            "capture_error": snapshot_summary.get("capture_error"),
            "live_semantics_ready": snapshot_summary.get("live_semantics_ready"),
            "degraded": snapshot_summary.get("degraded"),
            "degraded_reasons": snapshot_summary.get("degraded_reasons"),
        },
    }


def _poll_driver_settlement(driver: Any, *, prefer_live_semantics: bool = False) -> dict[str, Any]:
    snapshot_options = {"interactive_only": False, "compact": False}
    if prefer_live_semantics:
        snapshot_options["bridge_first_full"] = True

    settle = getattr(driver, "wait_for_state_settle", None)
    if callable(settle) and not prefer_live_semantics:
        return settle(
            timeout_ms=SETTLEMENT_TIMEOUT_MS,
            poll_ms=SETTLEMENT_POLL_MS,
            stable_observations=SETTLEMENT_STABLE_OBSERVATIONS,
            snapshot_options=snapshot_options,
        )

    started = time.monotonic()
    attempts = 0
    observed_stable = 0
    previous_fingerprint: tuple[Any, ...] | None = None
    last_snapshot: dict[str, Any] = {}
    stable_semantic_snapshot: dict[str, Any] | None = None
    stable_semantic_observations = 0
    while True:
        snapshot = driver.snapshot(dict(snapshot_options))
        last_snapshot = snapshot if isinstance(snapshot, dict) else {}
        attempts += 1
        elements = last_snapshot.get("elements", [])
        element_count = len(elements) if isinstance(elements, list) else -1
        fingerprint = (
            last_snapshot.get("tree_hash"),
            last_snapshot.get("screen_id"),
            last_snapshot.get("root"),
            element_count,
        )
        if previous_fingerprint is not None and fingerprint == previous_fingerprint:
            observed_stable += 1
        else:
            observed_stable = 1
        previous_fingerprint = fingerprint

        elapsed_ms = int((time.monotonic() - started) * 1000)
        snapshot_summary = _snapshot_introspection(last_snapshot) if last_snapshot else {}
        if bool(snapshot_summary.get("live_semantics_ready")) and observed_stable >= SETTLEMENT_STABLE_OBSERVATIONS:
            stable_semantic_snapshot = last_snapshot
            stable_semantic_observations = observed_stable
            return _settlement_result(
                status="settled",
                attempts=attempts,
                elapsed_ms=elapsed_ms,
                stable_observations=observed_stable,
                snapshot=last_snapshot,
            )
        if not prefer_live_semantics and observed_stable >= SETTLEMENT_STABLE_OBSERVATIONS:
            return _settlement_result(
                status="settled",
                attempts=attempts,
                elapsed_ms=elapsed_ms,
                stable_observations=observed_stable,
                snapshot=last_snapshot,
            )
        if elapsed_ms >= SETTLEMENT_TIMEOUT_MS:
            if isinstance(stable_semantic_snapshot, dict):
                return _settlement_result(
                    status="settled",
                    attempts=attempts,
                    elapsed_ms=elapsed_ms,
                    stable_observations=stable_semantic_observations,
                    snapshot=stable_semantic_snapshot,
                )
            return _settlement_result(
                status="timeout",
                attempts=attempts,
                elapsed_ms=elapsed_ms,
                stable_observations=observed_stable,
                snapshot=last_snapshot,
            )

        remaining_seconds = max(0.0, (SETTLEMENT_TIMEOUT_MS - elapsed_ms) / 1000.0)
        sleep_seconds = min(max(SETTLEMENT_POLL_MS, 0) / 1000.0, remaining_seconds)
        if sleep_seconds > 0:
            time.sleep(sleep_seconds)


def _settle_action(session: DeviceSession, operation: str, *, prefer_live_semantics: bool = False) -> dict[str, Any]:
    settle_result = _poll_driver_settlement(session.driver, prefer_live_semantics=prefer_live_semantics)
    snapshot = settle_result.get("snapshot")
    snapshot_summary = _snapshot_introspection(snapshot) if isinstance(snapshot, dict) else {}
    if isinstance(snapshot, dict):
        _seed_snapshot_cache(session, snapshot)

    status = "settled"
    details = "state settled via full operability snapshot"
    if settle_result.get("status") != "settled":
        status = "timeout"
        details = f"{operation} did not reach a stable page state before timeout"
    elif bool(snapshot_summary.get("degraded")):
        status = "degraded"
        details = f"{operation} settled on a degraded snapshot"

    return {
        "status": status,
        "details": details,
        "attempts": settle_result.get("attempts"),
        "elapsed_ms": settle_result.get("elapsed_ms"),
        "stable_observations": settle_result.get("stable_observations"),
        "tree_hash": settle_result.get("tree_hash"),
        "screen_id": snapshot_summary.get("screen_id"),
        "snapshot": snapshot_summary,
        "degraded": bool(snapshot_summary.get("degraded")),
        "degraded_reasons": list(snapshot_summary.get("degraded_reasons", [])),
    }


def _retry_selector_drift(
    session: DeviceSession,
    *,
    action: dict[str, Any],
    selector: dict[str, Any],
    result: dict[str, Any],
) -> dict[str, Any]:
    if result.get("status") not in {"error", "fail"} or result.get("error_code") != "selector_drift":
        return result

    full_snapshot = session.driver.snapshot({"interactive_only": False, "compact": False, "bridge_first_full": True})
    if not isinstance(full_snapshot, dict):
        return result

    retry_context = _selector_retry_context(selector, full_snapshot)
    retry_summary = retry_context.get("full_snapshot", {})
    if not bool(retry_summary.get("live_semantics_ready")):
        return {
            "status": "error",
            "error_code": "selector_retry_degraded",
            "details": "selector drift retry could not stay bridge-first because the full snapshot was degraded",
            "selector": selector,
            "retry_context": retry_context,
            "degraded": True,
            "degraded_reasons": list(retry_summary.get("degraded_reasons", [])),
        }

    retried = session.driver.interact(action, elements=_snapshot_elements(full_snapshot))
    retried = dict(retried)
    retried["retry_context"] = retry_context
    return retried


def _ambiguity_failure(selector: dict[str, Any], elements: list[dict[str, Any]] | None) -> dict[str, Any] | None:
    if str(selector.get("ambiguity_mode", "")) != "error":
        return None
    if not isinstance(elements, list):
        return None

    by = str(selector.get("by", "")).strip()
    value = selector.get("value")
    if not by or not isinstance(value, str) or not value:
        return None

    field_map = {
        "id": "id",
        "semantic_id": "semantic_id",
        "ref": "ref",
        "resource_id": "resource_id",
        "label": "label",
        "text": "text",
        "content_desc": "content_desc",
        "screen_id": "screen_id",
    }
    field_name = field_map.get(by)
    if field_name is None:
        return None

    matches = [
        element
        for element in elements
        if isinstance(element, dict) and isinstance(element.get(field_name), str) and str(element.get(field_name)) == value
    ]
    if len(matches) <= 1:
        return None

    candidates = [
        {
            key: match.get(key)
            for key in ("ref", "id", "screen_id", "semantic_id", "label", "path", "resource_id", "text", "content_desc", "class_name", "type")
        }
        for match in matches
    ]
    return {
        "status": "error",
        "error_code": "ambiguous_selector",
        "details": "selector matched multiple elements in ambiguity-safe mode",
        "selector": selector,
        "selector_info": {
            "match_type": "ambiguous",
            "candidate_count": len(matches),
        },
        "candidates": candidates,
    }


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
    search_fields = ("semantic_id", "id", "label", "text", "content_desc", "resource_id", "ref", "class_name", "type")
    field_priority = {
        "semantic_id": 0,
        "id": 1,
        "resource_id": 2,
        "label": 3,
        "text": 4,
        "content_desc": 5,
        "ref": 6,
        "class_name": 7,
        "type": 8,
    }
    if field != "any":
        if field not in search_fields:
            raise ValueError(f"unsupported find field: {field}")
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
            if score > best_score or (
                score == best_score
                and score > 0
                and field_priority.get(candidate_field, 99) < field_priority.get(best_field, 99)
            ):
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
            field_priority.get(str(item.get("match_field", "")), 99),
            str(item.get("path", "")),
            str(item.get("ref", "")),
        )
    )
    return results[: max(1, limit)]


def _load_session_from_file(path: Path) -> DeviceSession | None:
    if not path.exists():
        return None
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"invalid session payload at {path}")

    platform = str(raw.get("platform", ""))
    app = raw.get("app")
    if not isinstance(app, dict):
        raise ValueError(f"invalid session app at {path}")
    dispatch_commands = bool(raw.get("dispatch_commands", False))
    driver = _build_device_driver(platform, app, dispatch_commands)
    state = raw.get("state", {})
    if isinstance(state, dict):
        driver.restore_state(state)
    return DeviceSession(
        platform=platform,
        app=app,
        dispatch_commands=dispatch_commands,
        driver=driver,
    )


def _save_session_to_file(path: Path, session: DeviceSession) -> None:
    payload = {
        "platform": session.platform,
        "app": session.app,
        "dispatch_commands": session.dispatch_commands,
        "state": session.driver.dump_state(),
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=True), encoding="utf-8")


def _device_context(arguments: dict[str, Any]) -> tuple[str, Path, bool, bool | None]:
    session_file = _optional_str(arguments, "session_file")
    persist_session = bool(_optional_bool(arguments, "persist_session") or False)
    dispatch_override = _optional_bool(arguments, "dispatch_commands")
    path = _normalize_session_path(session_file)
    return str(path), path, persist_session, dispatch_override


def _device_session(arguments: dict[str, Any], require_existing: bool = True) -> tuple[DeviceSession | None, str, Path, bool, bool | None]:
    cache_key, session_path, persist_session, dispatch_override = _device_context(arguments)
    session = DEVICE_SESSION_CACHE.get(cache_key)
    if session is None:
        restored = _load_session_from_file(session_path)
        if restored is not None:
            session = restored
            DEVICE_SESSION_CACHE[cache_key] = restored

    if session is None and require_existing:
        raise ValueError(f"session not found: {session_path}; call device_open first")

    if session is not None and dispatch_override is not None and dispatch_override != session.dispatch_commands:
        raise ValueError("dispatch_commands mismatch with active session; reopen with device_open")

    return session, cache_key, session_path, persist_session, dispatch_override


def _preflight_prefers_semantic_settlement(preflight: dict[str, Any]) -> bool:
    bridge = preflight.get("bridge")
    if isinstance(bridge, dict):
        bridge_status = str(bridge.get("status", "")).strip().lower()
        if bridge_status in {"healthy", "ok", "ready", "connected"}:
            return True
        if bridge_status in {"error", "fail", "degraded", "offline", "disconnected"}:
            return False

    bridge_status = str(preflight.get("bridge_status", "")).strip().lower()
    return bridge_status in {"healthy", "ok", "ready", "connected"}


def _post_action_prefers_semantic_settlement(session: DeviceSession) -> bool:
    preflight = session.driver.preflight()
    if not isinstance(preflight, dict):
        return False
    return _preflight_prefers_semantic_settlement(preflight)


def _tool_device_open(arguments: dict[str, Any], runner: Runner) -> tuple[bool, dict[str, Any]]:
    _ = runner
    platform = _expect_str(arguments, "platform")
    app_id = _expect_str(arguments, "app")
    _, cache_key, session_path, persist_session, dispatch_override = _device_session(arguments, require_existing=False)

    dispatch_commands = dispatch_override if dispatch_override is not None else os.getenv("DISPATCH_COMMANDS", "0") == "1"
    if platform == "android":
        app = {"android_package": app_id}
    elif platform == "ios":
        app = {"ios_bundle_id": app_id}
    else:
        raise ValueError(f"unsupported platform: {platform}")

    driver = _build_device_driver(platform, app, dispatch_commands)
    launch = driver.interact({"action": "launch_app"})
    preflight = driver.preflight()

    session = DeviceSession(
        platform=platform,
        app=app,
        dispatch_commands=dispatch_commands,
        driver=driver,
    )
    DEVICE_SESSION_CACHE[cache_key] = session
    settlement: dict[str, Any] | None = None
    if launch.get("status") not in {"error", "fail"} and preflight.get("status") not in {"error", "fail"}:
        settlement = _settle_action(
            session,
            "open",
            prefer_live_semantics=_preflight_prefers_semantic_settlement(preflight),
        )
    if persist_session:
        _save_session_to_file(session_path, session)

    status = "ok"
    if launch.get("status") in {"error", "fail"} or preflight.get("status") in {"error", "fail"}:
        status = "error"
    if isinstance(settlement, dict) and settlement.get("status") == "timeout":
        status = "error"
    result_json = {
        "status": status,
        "operation": "open",
        "result": {"launch": launch, "preflight": preflight},
        "settlement": settlement,
    }

    payload = {
        "command": ["device_open"],
        "env_overrides": {"DISPATCH_COMMANDS": "1" if dispatch_commands else "0"},
        "exit_code": 0,
        "stdout": json.dumps(result_json, ensure_ascii=True),
        "stderr": "",
        "result_json": result_json,
        "session_file": str(session_path),
        "persist_session": persist_session,
    }
    return status == "error", payload


def _tool_device_snapshot(arguments: dict[str, Any], runner: Runner) -> tuple[bool, dict[str, Any]]:
    _ = runner
    interactive = _optional_bool(arguments, "interactive")
    compact = _optional_bool(arguments, "compact")
    refresh = bool(_optional_bool(arguments, "refresh") or False)
    session, _, session_path, persist_session, _ = _device_session(arguments, require_existing=True)
    assert session is not None

    interactive, compact = _resolve_snapshot_options(interactive=interactive, compact=compact)
    result_json, cache_hit = _cached_snapshot(
        session,
        interactive=interactive,
        compact=compact,
        refresh=refresh,
    )
    if persist_session:
        _save_session_to_file(session_path, session)

    payload = {
        "command": ["device_snapshot"],
        "env_overrides": {"DISPATCH_COMMANDS": "1" if session.dispatch_commands else "0"},
        "exit_code": 0,
        "stdout": json.dumps(result_json, ensure_ascii=True),
        "stderr": "",
        "result_json": result_json,
        "snapshot_options": {"interactive": interactive, "compact": compact},
        "cache_hit": cache_hit,
        "session_file": str(session_path),
        "persist_session": persist_session,
    }
    return False, payload


def _tool_device_list(arguments: dict[str, Any], runner: Runner) -> tuple[bool, dict[str, Any]]:
    _ = runner
    refresh = bool(_optional_bool(arguments, "refresh") or False)
    session, _, session_path, persist_session, _ = _device_session(arguments, require_existing=True)
    assert session is not None

    snapshot, cache_hit = _cached_snapshot(session, interactive=True, compact=True, refresh=refresh)
    elements = _compact_elements(snapshot)
    if persist_session:
        _save_session_to_file(session_path, session)

    payload = {
        "command": ["device_list"],
        "env_overrides": {"DISPATCH_COMMANDS": "1" if session.dispatch_commands else "0"},
        "exit_code": 0,
        "stdout": json.dumps(elements, ensure_ascii=True),
        "stderr": "",
        "result_json": elements,
        "cache_hit": cache_hit,
        "session_file": str(session_path),
        "persist_session": persist_session,
    }
    return False, payload


def _tool_device_find(arguments: dict[str, Any], runner: Runner) -> tuple[bool, dict[str, Any]]:
    _ = runner
    query = _expect_str(arguments, "query")
    field = _optional_str(arguments, "field") or "any"
    exact = bool(_optional_bool(arguments, "exact") or False)
    refresh = bool(_optional_bool(arguments, "refresh") or False)
    limit = _optional_int(arguments, "limit") or 20
    session, _, session_path, persist_session, _ = _device_session(arguments, require_existing=True)
    assert session is not None

    snapshot, cache_hit = _cached_snapshot(session, interactive=True, compact=True, refresh=refresh)
    elements = snapshot.get("elements", []) if isinstance(snapshot, dict) else []
    if not isinstance(elements, list):
        elements = []
    matches = _find_elements(elements, query, field=field, exact=exact, limit=limit)

    payload = {
        "command": ["device_find", query],
        "env_overrides": {"DISPATCH_COMMANDS": "1" if session.dispatch_commands else "0"},
        "exit_code": 0,
        "stdout": json.dumps(matches, ensure_ascii=True),
        "stderr": "",
        "result_json": matches,
        "query": query,
        "field": field,
        "exact": exact,
        "limit": max(1, limit),
        "cache_hit": cache_hit,
        "session_file": str(session_path),
        "persist_session": persist_session,
    }
    if persist_session:
        _save_session_to_file(session_path, session)
    return False, payload


def _tool_device_page_map(arguments: dict[str, Any], runner: Runner) -> tuple[bool, dict[str, Any]]:
    _ = runner
    refresh = bool(_optional_bool(arguments, "refresh") or False)
    session, _, session_path, persist_session, _ = _device_session(arguments, require_existing=True)
    assert session is not None

    snapshot, cache_hit = _cached_snapshot(session, interactive=False, compact=False, refresh=refresh)
    result_json = _build_page_map(snapshot)
    if persist_session:
        _save_session_to_file(session_path, session)

    payload = {
        "command": ["device_page_map"],
        "env_overrides": {"DISPATCH_COMMANDS": "1" if session.dispatch_commands else "0"},
        "exit_code": 0,
        "stdout": json.dumps(result_json, ensure_ascii=True),
        "stderr": "",
        "result_json": result_json,
        "cache_hit": cache_hit,
        "session_file": str(session_path),
        "persist_session": persist_session,
    }
    return False, payload


def _tool_device_element_dictionary(arguments: dict[str, Any], runner: Runner) -> tuple[bool, dict[str, Any]]:
    _ = runner
    refresh = bool(_optional_bool(arguments, "refresh") or False)
    fields_value = arguments.get("fields")
    fields: list[str] | None = None
    if fields_value is not None:
        if not isinstance(fields_value, list) or not all(isinstance(item, str) and item for item in fields_value):
            raise ValueError("'fields' must be an array of non-empty strings when provided")
        fields = list(fields_value)
    session, _, session_path, persist_session, _ = _device_session(arguments, require_existing=True)
    assert session is not None

    snapshot, cache_hit = _cached_snapshot(session, interactive=False, compact=False, refresh=refresh)
    result_json = _build_element_dictionary(snapshot, fields=fields)
    if persist_session:
        _save_session_to_file(session_path, session)

    payload = {
        "command": ["device_element_dictionary"],
        "env_overrides": {"DISPATCH_COMMANDS": "1" if session.dispatch_commands else "0"},
        "exit_code": 0,
        "stdout": json.dumps(result_json, ensure_ascii=True),
        "stderr": "",
        "result_json": result_json,
        "cache_hit": cache_hit,
        "session_file": str(session_path),
        "persist_session": persist_session,
    }
    return False, payload


def _tool_device_press(arguments: dict[str, Any], runner: Runner) -> tuple[bool, dict[str, Any]]:
    _ = runner
    session, _, session_path, persist_session, _ = _device_session(arguments, require_existing=True)
    assert session is not None

    selector, selector_supplied = _selector_from_arguments(arguments, session.platform)
    ambiguity_mode, candidate_limit = _selector_options(arguments, selector_supplied=selector_supplied)
    if ambiguity_mode is not None:
        selector["ambiguity_mode"] = ambiguity_mode
    if candidate_limit is not None:
        selector["candidate_limit"] = candidate_limit
    cached_elements = _cached_elements(session)
    result = _ambiguity_failure(selector, cached_elements)
    if result is None:
        result = session.driver.interact({"action": "tap", "selector": selector}, elements=cached_elements)
    result = _retry_selector_drift(
        session,
        action={"action": "tap", "selector": selector},
        selector=selector,
        result=result,
    )
    settlement: dict[str, Any] | None = None
    if result.get("status") not in {"error", "fail"}:
        prefer_live_semantics = _post_action_prefers_semantic_settlement(session)
        _invalidate_snapshot_cache(session)
        settlement = _settle_action(session, "press", prefer_live_semantics=prefer_live_semantics)
    if persist_session:
        _save_session_to_file(session_path, session)
    status = "error" if result.get("status") in {"error", "fail"} else "ok"
    if isinstance(settlement, dict) and settlement.get("status") == "timeout":
        status = "error"
    result_json = {"status": status, "operation": "press", "result": result, "settlement": settlement}
    command_target = selector.get("value")

    payload = {
        "command": ["device_press", str(command_target)],
        "env_overrides": {"DISPATCH_COMMANDS": "1" if session.dispatch_commands else "0"},
        "exit_code": 0,
        "stdout": json.dumps(result_json, ensure_ascii=True),
        "stderr": "",
        "result_json": result_json,
        "session_file": str(session_path),
        "persist_session": persist_session,
    }
    return status == "error", payload


def _tool_device_fill(arguments: dict[str, Any], runner: Runner) -> tuple[bool, dict[str, Any]]:
    _ = runner
    text = _expect_str(arguments, "text")
    session, _, session_path, persist_session, _ = _device_session(arguments, require_existing=True)
    assert session is not None

    selector, selector_supplied = _selector_from_arguments(arguments, session.platform)
    ambiguity_mode, candidate_limit = _selector_options(arguments, selector_supplied=selector_supplied)
    if ambiguity_mode is not None:
        selector["ambiguity_mode"] = ambiguity_mode
    if candidate_limit is not None:
        selector["candidate_limit"] = candidate_limit
    cached_elements = _cached_elements(session)
    result = _ambiguity_failure(selector, cached_elements)
    if result is None:
        result = session.driver.interact(
            {"action": "input_text", "selector": selector, "text": text},
            elements=cached_elements,
        )
    result = _retry_selector_drift(
        session,
        action={"action": "input_text", "selector": selector, "text": text},
        selector=selector,
        result=result,
    )
    settlement: dict[str, Any] | None = None
    if result.get("status") not in {"error", "fail"}:
        prefer_live_semantics = _post_action_prefers_semantic_settlement(session)
        _invalidate_snapshot_cache(session)
        settlement = _settle_action(session, "fill", prefer_live_semantics=prefer_live_semantics)
    if persist_session:
        _save_session_to_file(session_path, session)
    status = "error" if result.get("status") in {"error", "fail"} else "ok"
    if isinstance(settlement, dict) and settlement.get("status") == "timeout":
        status = "error"
    result_json = {"status": status, "operation": "fill", "result": result, "settlement": settlement}
    command_target = selector.get("value")

    payload = {
        "command": ["device_fill", str(command_target)],
        "env_overrides": {"DISPATCH_COMMANDS": "1" if session.dispatch_commands else "0"},
        "exit_code": 0,
        "stdout": json.dumps(result_json, ensure_ascii=True),
        "stderr": "",
        "result_json": result_json,
        "session_file": str(session_path),
        "persist_session": persist_session,
    }
    return status == "error", payload


def _tool_device_verify(arguments: dict[str, Any], runner: Runner) -> tuple[bool, dict[str, Any]]:
    _ = runner
    expected = _expect_str(arguments, "expected")
    timeout_ms = _optional_int(arguments, "timeout_ms")
    session, _, session_path, persist_session, _ = _device_session(arguments, require_existing=True)
    assert session is not None

    selector, selector_supplied = _selector_from_arguments(arguments, session.platform)
    ambiguity_mode, candidate_limit = _selector_options(arguments, selector_supplied=selector_supplied)
    if ambiguity_mode is not None:
        selector["ambiguity_mode"] = ambiguity_mode
    if candidate_limit is not None:
        selector["candidate_limit"] = candidate_limit
    cached_elements = _cached_elements(session)
    ambiguity_result = _ambiguity_failure(selector, cached_elements)
    if ambiguity_result is not None:
        result = ambiguity_result
        if persist_session:
            _save_session_to_file(session_path, session)
        result_json = {"status": "error", "operation": "verify", "result": result}
        command_target = selector.get("value")
        payload = {
            "command": ["device_verify", str(command_target)],
            "env_overrides": {"DISPATCH_COMMANDS": "1" if session.dispatch_commands else "0"},
            "exit_code": 0,
            "stdout": json.dumps(result_json, ensure_ascii=True),
            "stderr": "",
            "result_json": result_json,
            "session_file": str(session_path),
            "persist_session": persist_session,
        }
        return True, payload
    assertion = {"action": "assert_visible", "selector": selector, "timeout_ms": timeout_ms or 5000, "value": expected}
    result = session.driver.verify(assertion)
    if persist_session:
        _save_session_to_file(session_path, session)
    result_json = {"status": "ok", "operation": "verify", "result": result}
    command_target = selector.get("value")

    payload = {
        "command": ["device_verify", str(command_target)],
        "env_overrides": {"DISPATCH_COMMANDS": "1" if session.dispatch_commands else "0"},
        "exit_code": 0,
        "stdout": json.dumps(result_json, ensure_ascii=True),
        "stderr": "",
        "result_json": result_json,
        "session_file": str(session_path),
        "persist_session": persist_session,
    }
    return result.get("status") in {"error", "fail"} or result.get("verdict") == "fail", payload


TOOL_HANDLERS: dict[str, Callable[[dict[str, Any], Runner], tuple[bool, dict[str, Any]]]] = {
    "run_scenario": _tool_run_scenario,
    "evaluate_run": _tool_evaluate_run,
    "package_failure": _tool_package_failure,
    "replay_run": _tool_replay_run,
    "query_telemetry": _tool_query_telemetry,
    "update_selectors": _tool_update_selectors,
    "device_open": _tool_device_open,
    "device_snapshot": _tool_device_snapshot,
    "device_list": _tool_device_list,
    "device_find": _tool_device_find,
    "device_page_map": _tool_device_page_map,
    "device_element_dictionary": _tool_device_element_dictionary,
    "device_press": _tool_device_press,
    "device_fill": _tool_device_fill,
    "device_verify": _tool_device_verify,
}


def tool_schemas() -> list[dict[str, Any]]:
    return [
        {
            "name": "run_scenario",
            "description": "Run a scenario JSON on Android or iOS and produce a run directory.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "scenario": {"type": "string"},
                    "platform": {"type": "string", "enum": ["android", "ios"]},
                    "run_root": {"type": "string"},
                    "dispatch_commands": {"type": "boolean"},
                },
                "required": ["scenario", "platform"],
                "additionalProperties": False,
            },
        },
        {
            "name": "evaluate_run",
            "description": "Evaluate a completed run with oracle rules.",
            "inputSchema": {
                "type": "object",
                "properties": {"run_dir": {"type": "string"}, "rules": {"type": "string"}},
                "required": ["run_dir"],
                "additionalProperties": False,
            },
        },
        {
            "name": "package_failure",
            "description": "Create a failure bundle tarball from a run directory.",
            "inputSchema": {
                "type": "object",
                "properties": {"run_dir": {"type": "string"}},
                "required": ["run_dir"],
                "additionalProperties": False,
            },
        },
        {
            "name": "replay_run",
            "description": "Replay a run and compute structural consistency score.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "run_dir": {"type": "string"},
                    "mode": {"type": "string", "enum": ["structural"]},
                    "run_root": {"type": "string"},
                },
                "required": ["run_dir"],
                "additionalProperties": False,
            },
        },
        {
            "name": "query_telemetry",
            "description": "Search events in historical runs via key=value query filters.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "run_root": {"type": "string"},
                    "limit": {"type": "integer"},
                },
                "required": ["query"],
                "additionalProperties": False,
            },
        },
        {
            "name": "update_selectors",
            "description": "Repair ref selectors in a scenario using latest snapshot from a run.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "run_dir": {"type": "string"},
                    "session": {"type": "string"},
                    "output": {"type": "string"},
                },
                "required": ["run_dir"],
                "additionalProperties": False,
            },
        },
        {
            "name": "device_open",
            "description": "Open app in interactive device harness session.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "platform": {"type": "string", "enum": ["android", "ios"]},
                    "app": {"type": "string"},
                    "session_file": {"type": "string"},
                    "dispatch_commands": {"type": "boolean"},
                    "persist_session": {"type": "boolean"},
                },
                "required": ["platform", "app"],
                "additionalProperties": False,
            },
        },
        {
            "name": "device_snapshot",
            "description": "Capture compact accessibility snapshot from interactive session.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "session_file": {"type": "string"},
                    "interactive": {"type": "boolean"},
                    "compact": {"type": "boolean"},
                    "refresh": {"type": "boolean"},
                    "dispatch_commands": {"type": "boolean"},
                    "persist_session": {"type": "boolean"},
                },
                "required": [],
                "additionalProperties": False,
            },
        },
        {
            "name": "device_list",
            "description": "List selector-friendly elements from the interactive session.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "session_file": {"type": "string"},
                    "refresh": {"type": "boolean"},
                    "dispatch_commands": {"type": "boolean"},
                    "persist_session": {"type": "boolean"},
                },
                "required": [],
                "additionalProperties": False,
            },
        },
        {
            "name": "device_find",
            "description": "Find likely elements by query from interactive session snapshot.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "field": {
                        "type": "string",
                        "enum": ["any", "semantic_id", "id", "label", "text", "content_desc", "resource_id", "ref", "class_name", "type"],
                    },
                    "exact": {"type": "boolean"},
                    "limit": {"type": "integer"},
                    "refresh": {"type": "boolean"},
                    "session_file": {"type": "string"},
                    "dispatch_commands": {"type": "boolean"},
                    "persist_session": {"type": "boolean"},
                },
                "required": ["query"],
                "additionalProperties": False,
            },
        },
        {
            "name": "device_page_map",
            "description": "Build a current-screen page map from the interactive session snapshot.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "session_file": {"type": "string"},
                    "refresh": {"type": "boolean"},
                    "dispatch_commands": {"type": "boolean"},
                    "persist_session": {"type": "boolean"},
                },
                "required": [],
                "additionalProperties": False,
            },
        },
        {
            "name": "device_element_dictionary",
            "description": "Build a current-screen element dictionary grouped by stable text and id fields.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "fields": {"type": "array", "items": {"type": "string"}},
                    "session_file": {"type": "string"},
                    "refresh": {"type": "boolean"},
                    "dispatch_commands": {"type": "boolean"},
                    "persist_session": {"type": "boolean"},
                },
                "required": [],
                "additionalProperties": False,
            },
        },
        {
            "name": "device_press",
            "description": "Tap one element by legacy id/ref or by structured selector in interactive session.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "element": {"type": "string"},
                    "selector": {"type": "object"},
                    "ambiguity_mode": {"type": "string", "enum": ["first", "error"]},
                    "candidate_limit": {"type": "integer"},
                    "session_file": {"type": "string"},
                    "dispatch_commands": {"type": "boolean"},
                    "persist_session": {"type": "boolean"},
                },
                "required": [],
                "additionalProperties": False,
            },
        },
        {
            "name": "device_fill",
            "description": "Input text into an element in interactive session using a legacy id/ref or structured selector.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "element": {"type": "string"},
                    "selector": {"type": "object"},
                    "text": {"type": "string"},
                    "ambiguity_mode": {"type": "string", "enum": ["first", "error"]},
                    "candidate_limit": {"type": "integer"},
                    "session_file": {"type": "string"},
                    "dispatch_commands": {"type": "boolean"},
                    "persist_session": {"type": "boolean"},
                },
                "required": ["text"],
                "additionalProperties": False,
            },
        },
        {
            "name": "device_verify",
            "description": "Verify one element is visible in interactive session using a legacy id/ref or structured selector.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "element": {"type": "string"},
                    "selector": {"type": "object"},
                    "expected": {"type": "string"},
                    "timeout_ms": {"type": "integer"},
                    "ambiguity_mode": {"type": "string", "enum": ["first", "error"]},
                    "candidate_limit": {"type": "integer"},
                    "session_file": {"type": "string"},
                    "dispatch_commands": {"type": "boolean"},
                    "persist_session": {"type": "boolean"},
                },
                "required": ["expected"],
                "additionalProperties": False,
            },
        },
    ]


def execute_tool(name: str, arguments: dict[str, Any], runner: Runner = _run_command) -> tuple[bool, dict[str, Any]]:
    handler = TOOL_HANDLERS.get(name)
    if handler is None:
        raise KeyError(f"unknown tool: {name}")
    return handler(arguments, runner)


def _error(code: int, message: str, request_id: Any = None) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def _response(result: dict[str, Any], request_id: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _payload_text(name: str, payload: dict[str, Any], is_error: bool) -> str:
    status = "error" if is_error else "ok"
    parts = [f"{name}: {status}"]

    exit_code = payload.get("exit_code")
    if isinstance(exit_code, int):
        parts.append(f"exit_code={exit_code}")

    if "cache_hit" in payload:
        parts.append(f"cache_hit={bool(payload.get('cache_hit'))}")

    snapshot_options = payload.get("snapshot_options")
    if isinstance(snapshot_options, dict):
        parts.append(
            "snapshot_options="
            f"{int(bool(snapshot_options.get('interactive')))}:{int(bool(snapshot_options.get('compact')))}"
        )

    for key in ("run_dir", "bundle_path", "report_path", "replay_report_path", "updated_session_path", "session_file"):
        value = payload.get(key)
        if isinstance(value, str) and value:
            parts.append(f"{key}={value}")
            break

    query = payload.get("query")
    if isinstance(query, str) and query:
        parts.append(f"query={query}")

    result_json = payload.get("result_json")
    if isinstance(result_json, dict):
        snapshot_summary = result_json.get("snapshot")
        if isinstance(snapshot_summary, dict):
            screen_id = snapshot_summary.get("screen_id")
            if isinstance(screen_id, str) and screen_id:
                parts.append(f"screen_id={screen_id}")
            capture_source = snapshot_summary.get("capture_source")
            if isinstance(capture_source, str) and capture_source:
                parts.append(f"capture_source={capture_source}")
            semantic_id_count = snapshot_summary.get("semantic_id_count")
            if isinstance(semantic_id_count, int):
                parts.append(f"semantic_ids={semantic_id_count}")
            if bool(snapshot_summary.get("degraded")):
                parts.append("degraded=true")

        summary = result_json.get("summary")
        if isinstance(summary, dict):
            ambiguous_entry_count = summary.get("ambiguous_entry_count")
            if isinstance(ambiguous_entry_count, int):
                parts.append(f"ambiguous_entries={ambiguous_entry_count}")

        settlement = result_json.get("settlement")
        if isinstance(settlement, dict):
            settlement_status = settlement.get("status")
            if isinstance(settlement_status, str) and settlement_status:
                parts.append(f"settlement={settlement_status}")
            if bool(settlement.get("degraded")):
                parts.append("degraded=true")

    return "; ".join(parts)


class MCPServer:
    def __init__(self, runner: Runner = _run_command):
        self._runner = runner

    def handle_message(self, message: dict[str, Any]) -> dict[str, Any] | None:
        request_id = message.get("id")
        method = message.get("method")
        if not isinstance(method, str):
            return _error(-32600, "invalid request: missing method", request_id)

        if method == "notifications/initialized":
            return None
        if method == "ping":
            return _response({}, request_id)
        if method == "initialize":
            params = message.get("params", {})
            protocol_version = PROTOCOL_VERSION
            if isinstance(params, dict):
                client_protocol = params.get("protocolVersion")
                if isinstance(client_protocol, str) and client_protocol:
                    protocol_version = client_protocol
            return _response(
                {
                    "protocolVersion": protocol_version,
                    "capabilities": {"tools": {"listChanged": False}},
                    "serverInfo": SERVER_INFO,
                },
                request_id,
            )
        if method == "tools/list":
            return _response({"tools": tool_schemas()}, request_id)
        if method == "resources/list":
            return _response({"resources": []}, request_id)
        if method == "prompts/list":
            return _response({"prompts": []}, request_id)
        if method == "tools/call":
            params = message.get("params", {})
            if not isinstance(params, dict):
                return _error(-32602, "invalid params for tools/call", request_id)
            name = params.get("name")
            if not isinstance(name, str) or not name:
                return _error(-32602, "tool name is required", request_id)
            arguments = params.get("arguments", {})
            if arguments is None:
                arguments = {}
            if not isinstance(arguments, dict):
                return _error(-32602, "tool arguments must be an object", request_id)

            try:
                is_error, payload = execute_tool(name, arguments, runner=self._runner)
            except KeyError:
                return _error(-32602, f"unknown tool: {name}", request_id)
            except ValueError as exc:
                return _error(-32602, str(exc), request_id)
            except Exception as exc:  # pragma: no cover - defensive path
                return _error(-32000, f"tool execution failed: {exc}", request_id)

            return _response(
                {
                    "content": [{"type": "text", "text": _payload_text(name, payload, is_error)}],
                    "structuredContent": payload,
                    "isError": is_error,
                },
                request_id,
            )

        return _error(-32601, f"method not found: {method}", request_id)


def _read_message(input_stream: Any) -> tuple[dict[str, Any] | None, str | None]:
    """
    Read one MCP message from stdin.

    Supports both:
    - Header-framed transport (Content-Length + JSON body)
    - JSONL transport (one JSON object per line)
    """
    headers: dict[str, str] = {}

    while True:
        line = input_stream.readline()
        if line == b"":
            return None, None

        stripped = line.strip()
        if not stripped:
            continue

        # JSONL mode: line is already a complete JSON-RPC message.
        if stripped.startswith(b"{") or stripped.startswith(b"["):
            return json.loads(stripped.decode("utf-8")), "jsonl"

        raw = line.decode("ascii", errors="replace").strip()
        if ":" not in raw:
            # Ignore unknown prelude lines and keep reading.
            continue

        key, value = raw.split(":", 1)
        normalized_key = key.strip().lower().lstrip("\ufeff")
        headers[normalized_key] = value.strip()
        break

    while True:
        line = input_stream.readline()
        if line == b"":
            raise ValueError("incomplete message headers")
        if line in (b"\r\n", b"\n"):
            break
        raw = line.decode("ascii", errors="replace").strip()
        if ":" not in raw:
            continue
        key, value = raw.split(":", 1)
        normalized_key = key.strip().lower().lstrip("\ufeff")
        headers[normalized_key] = value.strip()

    content_length = int(headers.get("content-length", "0"))
    if content_length <= 0:
        raise ValueError("missing content-length header")
    body = input_stream.read(content_length)
    if len(body) != content_length:
        raise ValueError("incomplete message body")
    return json.loads(body.decode("utf-8")), "lsp"


def _write_message(output_stream: Any, payload: dict[str, Any], transport_mode: str = "lsp") -> None:
    body = json.dumps(payload, ensure_ascii=True).encode("utf-8")
    if transport_mode == "jsonl":
        output_stream.write(body + b"\n")
        output_stream.flush()
        return

    header = f"Content-Length: {len(body)}\r\n\r\n".encode("ascii")
    output_stream.write(header)
    output_stream.write(body)
    output_stream.flush()


def serve_forever(server: MCPServer) -> None:
    transport_mode = "lsp"
    while True:
        try:
            message, detected_mode = _read_message(sys.stdin.buffer)
            if detected_mode:
                transport_mode = detected_mode
        except json.JSONDecodeError:
            _write_message(sys.stdout.buffer, _error(-32700, "parse error", None), transport_mode=transport_mode)
            continue
        except ValueError as exc:
            _write_message(sys.stdout.buffer, _error(-32600, str(exc), None), transport_mode=transport_mode)
            continue

        if message is None:
            return
        if not isinstance(message, dict):
            _write_message(
                sys.stdout.buffer,
                _error(-32600, "invalid request payload", None),
                transport_mode=transport_mode,
            )
            continue

        response = server.handle_message(message)
        if response is not None and message.get("id") is not None:
            _write_message(sys.stdout.buffer, response, transport_mode=transport_mode)


def main() -> None:
    serve_forever(MCPServer())


if __name__ == "__main__":
    main()
