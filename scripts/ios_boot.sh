#!/usr/bin/env bash
set -euo pipefail

SIMULATOR_NAME="${IOS_SIMULATOR_NAME:-iPhone 16}"

xcrun simctl boot "$SIMULATOR_NAME" || true
open -a Simulator
