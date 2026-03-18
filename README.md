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
  - includes `android-bridge-contract.md` for app-side bridge integration.
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

## MCP server

This repo includes a stdio MCP server so AI clients can call harness tools directly.

Run locally:

```bash
make mcp
# or
python3 tools/mcp_server.py
```

Exposed MCP tools include:
- `run_scenario`
- `evaluate_run`
- `package_failure`
- `replay_run`
- `query_telemetry`
- `update_selectors`
- `device_open`
- `device_snapshot`
- `device_press`
- `device_fill`
- `device_verify`

Notes for high-frequency `device_*` calls:
- MCP server now executes `device_*` tools in-process with a cached session (no per-call Python subprocess spawn).
- Optional `persist_session=true` writes session state to `session_file` for cross-process recovery.

Example MCP client config (adjust absolute path):

```json
{
  "mcpServers": {
    "mobile-harness": {
      "command": "python3",
      "args": ["/Users/josh_folder/scaffold/tools/mcp_server.py"]
    }
  }
}
```

## Current state

This scaffold now emits per-step evidence artifacts (`snapshots/*.json`, `diffs/*.json`, `raw_trees/*.json`, `capture_traces/*.json`, `events.jsonl`) and evaluates runs using structural checks.

Android dispatch mode (`DISPATCH_COMMANDS=1`) uses an accessibility bridge contract (`adb forward + HTTP`) for real UI tree capture (`cat.v2`). If the target app does not expose a ready bridge endpoint, the run hard-fails with explicit diagnostics (`bridge_not_integrated`).

iOS interactive control still uses a lightweight placeholder bridge by default; connect XCTest/WDA for production-grade interactions.

## Unified CLI

`tools/device_harness.py` offers a single interface across platforms:

```bash
python3 tools/device_harness.py open --platform android com.example.app
python3 tools/device_harness.py snapshot -i -c
python3 tools/device_harness.py press @e123456789
python3 tools/device_harness.py fill search_box "hello"
python3 tools/device_harness.py verify home_screen "home"
```

## Live Android Verification

Use `tools/live_android_verify.py` to validate the real post-`open` chain on a connected emulator/device and get JSON diagnostics when semantics drift from actual UI state.

```bash
python3 tools/live_android_verify.py \
  --app com.utell.youtiao \
  --serial emulator-5554 \
  --press-target todo_calendar.search_bar \
  --fill-target search.query_input \
  --fill-text livecheck123
```

The script reuses `device_open`, `device_page_map`, `device_element_dictionary`, `device_press`, `device_fill`, `device_verify`, `inspect_android_bridge.py`, and an ADB `uiautomator dump` cross-check so it can distinguish:
- bridge not healthy
- bridge semantics not live
- fill succeeded at transport level but text never appeared
- fill changed the real UI but bridge semantics stayed stale
