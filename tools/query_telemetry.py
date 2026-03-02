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


def _parse_query(query: str) -> dict[str, str]:
    filters: dict[str, str] = {}
    for token in query.split():
        if "=" not in token:
            continue
        key, value = token.split("=", 1)
        filters[key.strip()] = value.strip()
    return filters


def _read_events(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    events: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        events.append(json.loads(line))
    return events


def _event_matches(event: dict[str, Any], filters: dict[str, str]) -> bool:
    for key, value in filters.items():
        if key == "action" and str(event.get("action")) != value:
            return False
        if key == "phase" and str(event.get("phase")) != value:
            return False
        if key == "ref":
            selector = event.get("metadata", {}).get("selector", {})
            resolved_ref = event.get("result", {}).get("selector_info", {}).get("resolved_ref")
            if str(selector.get("value")) != value and str(resolved_ref) != value:
                return False
        if key == "success":
            status = str(event.get("result", {}).get("status", ""))
            expected = value.lower() in {"true", "1", "yes"}
            is_success = status not in {"error", "fail"}
            if expected != is_success:
                return False
        if key == "error_code":
            if str(event.get("result", {}).get("error_code", "")) != value:
                return False
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description="Query telemetry events from historical run directories.")
    parser.add_argument("--query", required=True, help="Space-separated key=value filters")
    parser.add_argument("--run-root", default="runs")
    parser.add_argument("--limit", type=int, default=100)
    args = parser.parse_args()

    filters = _parse_query(args.query)
    run_root = Path(args.run_root)
    run_dirs = sorted((path for path in run_root.glob("*") if path.is_dir()), reverse=True)

    matches: list[dict[str, Any]] = []
    for run_dir in run_dirs:
        events = _read_events(run_dir / "events.jsonl")
        for event in events:
            if _event_matches(event, filters):
                matches.append(
                    {
                        "run_id": run_dir.name,
                        "ts": event.get("ts"),
                        "phase": event.get("phase"),
                        "action": event.get("action"),
                        "status": event.get("result", {}).get("status"),
                        "error_code": event.get("result", {}).get("error_code"),
                        "resolved_ref": event.get("result", {}).get("selector_info", {}).get("resolved_ref"),
                    }
                )
                if len(matches) >= args.limit:
                    break
        if len(matches) >= args.limit:
            break

    summary = {
        "filters": filters,
        "run_root": str(run_root),
        "count": len(matches),
        "matches": matches,
    }
    print(json.dumps(summary, indent=2, ensure_ascii=True))


if __name__ == "__main__":
    main()
