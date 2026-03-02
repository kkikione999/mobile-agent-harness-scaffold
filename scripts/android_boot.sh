#!/usr/bin/env bash
set -euo pipefail

AVD_NAME="${ANDROID_AVD_NAME:-Pixel_8_API_34}"

emulator -avd "$AVD_NAME" -no-snapshot-load -netdelay none -netspeed full
