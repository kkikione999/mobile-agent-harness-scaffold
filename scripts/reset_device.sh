#!/usr/bin/env bash
set -euo pipefail

ANDROID_PACKAGE="${ANDROID_PACKAGE:-com.example.app}"
IOS_BUNDLE_ID="${IOS_BUNDLE_ID:-com.example.app}"
IOS_SIMULATOR_NAME="${IOS_SIMULATOR_NAME:-iPhone 16}"

adb shell pm clear "$ANDROID_PACKAGE" || true
xcrun simctl terminate "$IOS_SIMULATOR_NAME" "$IOS_BUNDLE_ID" || true
