from __future__ import annotations

import unittest

from tools import query_telemetry


class TestQueryTelemetry(unittest.TestCase):
    def test_event_matches_filters_by_run_id(self) -> None:
        event = {"action": "launch_app", "phase": "driver", "result": {"status": "ok"}, "metadata": {}}

        self.assertTrue(query_telemetry._event_matches(event, {"run_id": "run-1"}, "run-1"))
        self.assertFalse(query_telemetry._event_matches(event, {"run_id": "run-2"}, "run-1"))

    def test_event_matches_supports_combined_filters(self) -> None:
        event = {
            "action": "launch_app",
            "phase": "driver",
            "result": {"status": "ok", "selector_info": {"resolved_ref": "@e1"}},
            "metadata": {"schema_version": "cat.v2", "app_integration_status": "ok"},
        }
        filters = {"run_id": "run-1", "action": "launch_app", "schema_version": "cat.v2"}
        self.assertTrue(query_telemetry._event_matches(event, filters, "run-1"))


if __name__ == "__main__":
    unittest.main()
