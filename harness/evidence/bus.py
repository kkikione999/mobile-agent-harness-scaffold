from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass
class EvidenceBus:
    run_dir: Path
    events_path: Path = field(init=False)
    summary_path: Path = field(init=False)
    snapshots_dir: Path = field(init=False)
    diffs_dir: Path = field(init=False)
    counts: dict[str, int] = field(
        default_factory=lambda: {
            "events": 0,
            "errors": 0,
            "assertions": 0,
            "selector_drifts": 0,
        }
    )

    def __post_init__(self) -> None:
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.events_path = self.run_dir / "events.jsonl"
        self.summary_path = self.run_dir / "summary.json"
        self.snapshots_dir = self.run_dir / "snapshots"
        self.diffs_dir = self.run_dir / "diffs"
        self.snapshots_dir.mkdir(parents=True, exist_ok=True)
        self.diffs_dir.mkdir(parents=True, exist_ok=True)

    def write_snapshot(self, step_index: int, label: str, payload: dict[str, Any]) -> str:
        rel_path = Path("snapshots") / f"{step_index:03d}-{label}.json"
        abs_path = self.run_dir / rel_path
        abs_path.write_text(json.dumps(payload, indent=2, ensure_ascii=True), encoding="utf-8")
        return str(rel_path)

    def write_diff(self, step_index: int, payload: dict[str, Any]) -> str:
        rel_path = Path("diffs") / f"{step_index:03d}.json"
        abs_path = self.run_dir / rel_path
        abs_path.write_text(json.dumps(payload, indent=2, ensure_ascii=True), encoding="utf-8")
        return str(rel_path)

    def record_event(
        self,
        phase: str,
        action: str,
        command: str | None,
        result: dict[str, Any],
        step_index: int | None = None,
        evidence: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        event = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "phase": phase,
            "action": action,
            "command": command,
            "result": result,
        }
        if step_index is not None:
            event["step_index"] = step_index
        if evidence:
            event["evidence"] = evidence
        if metadata:
            event["metadata"] = metadata

        with self.events_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(event, ensure_ascii=True) + "\n")

        self.counts["events"] += 1
        if phase == "assertion":
            self.counts["assertions"] += 1
        if result.get("status") in {"error", "fail"} or result.get("verdict") == "fail":
            self.counts["errors"] += 1
        if result.get("error_code") == "selector_drift":
            self.counts["selector_drifts"] += 1

    def finalize(self, extra: dict[str, Any] | None = None) -> None:
        payload = dict(self.counts)
        if extra:
            payload.update(extra)
        self.summary_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
