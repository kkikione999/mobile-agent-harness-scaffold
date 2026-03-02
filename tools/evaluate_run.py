#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from harness.oracle.evaluator import evaluate


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate one run directory with oracle rules.")
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--rules", default="rules/oracle_rules.json")
    args = parser.parse_args()

    report = evaluate(Path(args.run_dir), Path(args.rules))
    status = "PASS" if report["passed"] else "FAIL"
    print(f"oracle result: {status}")
    print(f"report: {Path(args.run_dir) / 'oracle_report.json'}")


if __name__ == "__main__":
    main()
