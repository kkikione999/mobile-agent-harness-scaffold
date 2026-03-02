# Mobile Agent Harness Scaffold

A practical starter repository for building an AI-first test harness that can control, observe, and verify app behavior on Android Emulator and iOS Simulator.

## Why this scaffold

This repo gives you a minimal but runnable shape for:
- a unified action DSL (`scenarios/*.json`)
- platform harness adapters (`harness/driver`)
- evidence capture with snapshots + structural diffs (`harness/evidence`)
- oracle evaluation with evidence checks (`harness/oracle`)
- failure triage bundling (`harness/triage`)

## Repository map

- `AGENTS.md`: AI contribution and review guardrails.
- `config/`: Device and environment templates.
- `docs/`: Architecture, oracle rules, and repro playbook.
- `harness/`: Core runtime components.
- `rules/`: Machine-checkable oracle thresholds.
- `scenarios/`: Executable scenarios in DSL JSON.
- `tools/`: CLI entrypoints.
- `scripts/`: Device boot/reset helpers.
- `runs/`: Runtime evidence output (generated).

## Quick start

```bash
make check
make run-smoke-android
make eval RUN_DIR=runs/<run-id>
make replay RUN_DIR=runs/<run-id>
```

For iOS:

```bash
make run-smoke-ios
```

## Current state

This scaffold now emits per-step evidence artifacts (`snapshots/*.json`, `diffs/*.json`, `events.jsonl`) and evaluates runs using structural checks. iOS interactive control still uses a lightweight placeholder bridge by default; connect XCTest/WDA for production-grade interactions.

## Unified CLI

`tools/device_harness.py` offers a single interface across platforms:

```bash
python3 tools/device_harness.py open --platform android com.example.app
python3 tools/device_harness.py snapshot -i -c
python3 tools/device_harness.py press @e123456789
python3 tools/device_harness.py fill search_box "hello"
python3 tools/device_harness.py verify home_screen "home"
```
