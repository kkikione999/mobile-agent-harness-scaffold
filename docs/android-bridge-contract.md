# Android Accessibility Bridge Contract

Android dispatch mode (`DISPATCH_COMMANDS=1`) expects the target app to expose a local HTTP bridge reachable through `adb forward`.

## Transport

- Local endpoint: `http://127.0.0.1:${ANDROID_BRIDGE_LOCAL_PORT}`.
- Device endpoint: `127.0.0.1:${ANDROID_BRIDGE_REMOTE_PORT}`.
- Harness creates tunnel with `adb forward tcp:<local> tcp:<remote>`.

## Health API

- `GET /health?package=<android_package>`
- Response (`200`):

```json
{
  "ready": true,
  "package": "com.example.app",
  "protocol_version": "bridge.v1",
  "diagnostics": {
    "warnings": []
  }
}
```

When `ready=false` or package mismatch, harness reports `bridge_not_integrated` and fails preflight.

## Snapshot API

- `POST /tree/snapshot`
- Request body:

```json
{
  "request_id": "uuid",
  "package": "com.example.app",
  "interactive_only": true,
  "compact": true,
  "include_invisible": false,
  "timeout_ms": 3000
}
```

- Response (`200`):

```json
{
  "request_id": "uuid",
  "protocol_version": "bridge.v1",
  "root": "node-0",
  "nodes": [
    {
      "node_id": "node-0",
      "parent_id": null,
      "class_name": "android.widget.FrameLayout",
      "resource_id": "com.example:id/root",
      "text": "",
      "content_desc": "Root",
      "bounds": [0, 0, 1080, 2400],
      "clickable": false,
      "enabled": true,
      "visible": true,
      "focusable": false,
      "checked": false,
      "selected": false,
      "editable": false,
      "index_in_parent": 0
    }
  ],
  "diagnostics": {
    "warnings": []
  }
}
```

The harness normalizes this payload to `cat.v2` and emits evidence files for raw payloads and normalized snapshots.
