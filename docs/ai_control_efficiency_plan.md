# AI Control Efficiency Implementation Plan

## Goal
Reduce latency and failure rate when AI locates pages/elements and executes interactions on Android simulator sessions.

## Current Bottlenecks
- Repeated full snapshots for list/find/press/fill flows.
- AI must grep large element lists manually.
- Selector resolution does not always reuse already-captured elements.
- Chinese multiline input is not a first-class harness action.

## Phase 1: Selector Discovery and Snapshot Reuse

### Scope
- Add `device_find` capability for fast element lookup by text/label/content/id/ref.
- Add session-level snapshot cache and allow reusing cached elements for `device_press` and `device_fill`.
- Keep current behavior as fallback when cache is missing.

### Files
- `tools/mcp_server.py`
- `tools/device_harness.py`
- `tests/test_mcp_server.py`

### Acceptance
- `device_find` returns ranked matches without requiring client-side grep.
- `device_press` and `device_fill` can resolve selectors using cached elements.
- Cache invalidates after mutating actions.

### Tests
- `python3 -m unittest tests.test_mcp_server`

## Phase 2: Intent-Level Navigation Primitives

### Scope
- Add high-level actions (`open_settings`, `open_theme_picker`, `save_current_editor`) that map to stable selectors by semantic priority.
- Add fallback chain for text mismatch (id -> content_desc -> label -> anchor).

### Files
- `harness/driver/selectors.py`
- `tools/mcp_server.py`
- `tests/test_selectors.py`

### Acceptance
- High-level intents execute with fewer discovery calls.
- Selector drift rate decreases on repeated runs.

### Tests
- `python3 -m unittest tests.test_selectors tests.test_mcp_server`

## Phase 2.5: Page Map And Ambiguity-Safe Resolution

### Scope
- Add `device_page_map` and `device_element_dictionary` so agents can inspect the current screen before acting.
- Extend selector resolution with ambiguity-safe mode so repeated matches fail closed instead of silently resolving by path order.
- Allow `device_press`, `device_fill`, and `device_verify` to accept structured selectors while keeping legacy `element` support.

### Files
- `harness/driver/selectors.py`
- `harness/driver/device_bridge.py`
- `tools/mcp_server.py`
- `tests/test_selectors.py`
- `tests/test_mcp_server.py`

### Acceptance
- Agents can request a current-screen structure summary without manually scanning the full raw snapshot.
- Agents can request a grouped dictionary of current-screen ids, labels, and visible text values.
- Structured selectors can opt into ambiguity-safe mode and receive `ambiguous_selector` plus candidates when resolution is not unique.
- Legacy `element` calls still work unchanged.

### Tests
- `python3 -m unittest tests.test_selectors tests.test_mcp_server`

## Phase 3: Multiline Unicode Input in Harness

### Scope
- Add first-class `input_multiline` tool/action using safe transport (`ADB IME broadcast`/`b64`) for Chinese and newline.
- Remove need for ad-hoc direct adb commands in operator workflow.

### Files
- `harness/driver/android.py`
- `tools/mcp_server.py`
- `tools/device_harness.py`
- `tests/test_mcp_server.py`

### Acceptance
- Chinese + newline input works via harness-only workflow.
- Save flow can be fully scripted without manual adb fallback.

### Tests
- `python3 -m unittest tests.test_mcp_server tests.test_device_harness`

## Operational Verification
After each phase:
1. `make check`
2. `make run-smoke-android`
3. `make eval RUN_DIR=<latest-run-dir>`

## Rollback Strategy
- Keep new features additive.
- Guard with optional arguments and preserve legacy behavior paths.
