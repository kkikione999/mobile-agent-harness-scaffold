from __future__ import annotations

import tarfile
from pathlib import Path


def create_failure_bundle(run_dir: Path) -> Path:
    output = run_dir / "failure_bundle.tar.gz"
    include_files = [
        "events.jsonl",
        "summary.json",
        "run_meta.json",
        "oracle_report.json",
        "replay_report.json",
    ]
    include_dirs = ["snapshots", "diffs", "raw_trees", "capture_traces"]

    with tarfile.open(output, "w:gz") as tar:
        for name in include_files:
            path = run_dir / name
            if path.exists():
                tar.add(path, arcname=name)
        for name in include_dirs:
            path = run_dir / name
            if path.exists():
                tar.add(path, arcname=name)

    return output
