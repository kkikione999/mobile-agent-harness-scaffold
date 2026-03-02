# AGENTS

## Purpose

Keep this repo deterministic, observable, and machine-verifiable for mobile simulator testing.

## Ground rules

- Do not add new scenario formats without updating `harness/driver/dsl.py` and `tests/`.
- Keep all harness logic platform-neutral first, then add per-platform adapters.
- Every scenario should emit evidence into `runs/<run-id>/`.
- Every failed run should be packageable with `tools/package_failure.py`.

## Required checks

Before opening a PR:

1. `make check`
2. `make run-smoke-android` or `make run-smoke-ios`
3. `make eval RUN_DIR=<last-run-dir>`

## Definition of done

A harness change is complete only if:
- It keeps run artifacts reproducible.
- It does not break existing scenario loading.
- It includes at least one assertion path that oracle can evaluate.
