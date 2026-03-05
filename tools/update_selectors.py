#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from harness.driver.selectors import build_anchor, resolve_selector


def _parse_point(step: dict[str, Any]) -> tuple[float, float] | None:
    if "x" not in step or "y" not in step:
        return None
    try:
        return float(step["x"]), float(step["y"])
    except (TypeError, ValueError):
        return None


def _parse_bounds(bounds: Any) -> tuple[float, float, float, float] | None:
    if not isinstance(bounds, list) or len(bounds) != 4:
        return None
    try:
        left, top, right, bottom = [float(value) for value in bounds]
    except (TypeError, ValueError):
        return None
    if right < left or bottom < top:
        return None
    return left, top, right, bottom


def _match_by_point(
    point: tuple[float, float],
    elements: list[dict[str, Any]],
) -> dict[str, Any] | None:
    x, y = point
    candidates: list[tuple[float, str, dict[str, Any]]] = []
    for element in elements:
        bounds = _parse_bounds(element.get("bounds"))
        if not bounds:
            continue
        left, top, right, bottom = bounds
        if left <= x <= right and top <= y <= bottom:
            area = (right - left) * (bottom - top)
            candidates.append((area, str(element.get("path", "")), element))

    if not candidates:
        return None
    candidates.sort(key=lambda item: (item[0], item[1]))
    return candidates[0][2]


def _load_snapshot(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _load_latest_tree(run_dir: Path) -> dict[str, Any]:
    snapshot_dir = run_dir / "snapshots"
    if not snapshot_dir.exists():
        return {}
    candidates = sorted(snapshot_dir.glob("*-after.json"))
    if not candidates:
        return {}
    return _load_snapshot(candidates[-1])


def _update_steps(steps: list[dict[str, Any]], elements: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    updated_steps: list[dict[str, Any]] = []
    updates: list[dict[str, Any]] = []

    for idx, step in enumerate(steps):
        new_step = dict(step)
        selector = new_step.get("selector")
        if step.get("action") == "tap" and selector is None:
            point = _parse_point(new_step)
            if point is not None:
                matched = _match_by_point(point, elements)
                if matched is None:
                    updated_steps.append(new_step)
                    updates.append(
                        {
                            "index": idx,
                            "action": step.get("action"),
                            "status": "unresolved",
                            "matched_ref": None,
                        }
                    )
                    continue
                anchor = matched.get("anchor")
                if not isinstance(anchor, dict):
                    anchor = build_anchor(matched)
                new_step.pop("x", None)
                new_step.pop("y", None)
                new_step["selector"] = {
                    "by": "ref",
                    "value": str(matched.get("ref")),
                    "anchor": anchor,
                }
                updated_steps.append(new_step)
                updates.append(
                    {
                        "index": idx,
                        "action": step.get("action"),
                        "status": "updated",
                        "matched_ref": str(matched.get("ref")),
                    }
                )
                continue
        if not isinstance(selector, dict) or selector.get("by") != "ref":
            updated_steps.append(new_step)
            continue

        current_ref = str(selector.get("value", ""))
        matched, info = resolve_selector(selector, elements)
        if matched is None:
            updated_steps.append(new_step)
            updates.append(
                {
                    "index": idx,
                    "action": step.get("action"),
                    "status": "unresolved",
                    "old_ref": current_ref,
                    "matched_ref": None,
                    "match_type": info.get("match_type"),
                    "confidence": info.get("confidence"),
                }
            )
            continue

        new_ref = str(matched.get("ref"))
        new_selector = dict(selector)
        new_selector["value"] = new_ref
        new_selector["anchor"] = matched.get("anchor")
        new_step["selector"] = new_selector
        updated_steps.append(new_step)
        updates.append(
            {
                "index": idx,
                "action": step.get("action"),
                "status": "updated" if new_ref != current_ref else "unchanged",
                "old_ref": current_ref,
                "new_ref": new_ref,
                "matched_ref": new_ref,
                "confidence": info.get("confidence"),
            }
        )
    return updated_steps, updates


def main() -> None:
    parser = argparse.ArgumentParser(description="Repair drifted selector refs using latest run snapshot.")
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--session", help="Scenario/session JSON to update. Defaults to run_meta scenario_path.")
    parser.add_argument("--output", help="Write updated session to this path. Defaults to <session>.updated.json")
    args = parser.parse_args()

    run_dir = Path(args.run_dir)
    meta = json.loads((run_dir / "run_meta.json").read_text(encoding="utf-8"))
    session_path = Path(args.session) if args.session else Path(meta["scenario_path"])
    session = json.loads(session_path.read_text(encoding="utf-8"))

    latest_tree = _load_latest_tree(run_dir)
    elements = latest_tree.get("elements", [])
    if not elements:
        raise SystemExit(f"no snapshot elements found in {run_dir / 'snapshots'}")

    updated_steps, updates = _update_steps(list(session.get("steps", [])), elements)
    session["steps"] = updated_steps

    output = Path(args.output) if args.output else session_path.with_suffix(".updated.json")
    output.write_text(json.dumps(session, indent=2, ensure_ascii=True), encoding="utf-8")

    report = {
        "run_dir": str(run_dir),
        "session_in": str(session_path),
        "session_out": str(output),
        "updates": updates,
    }
    report_path = run_dir / "selector_update_report.json"
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=True), encoding="utf-8")

    print(f"updated session: {output}")
    print(f"selector report: {report_path}")


if __name__ == "__main__":
    main()
