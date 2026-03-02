#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from harness.triage.bundle import create_failure_bundle


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a failure bundle tarball from a run dir.")
    parser.add_argument("--run-dir", required=True)
    args = parser.parse_args()

    output = create_failure_bundle(Path(args.run_dir))
    print(f"bundle: {output}")


if __name__ == "__main__":
    main()
