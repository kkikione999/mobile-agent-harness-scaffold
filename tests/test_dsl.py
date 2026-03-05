from __future__ import annotations

import json
import os
import tempfile
import unittest
from typing import Any

from harness.driver.dsl import load_scenario


class TestDSL(unittest.TestCase):
    def test_load_android_smoke(self) -> None:
        scenario = load_scenario("scenarios/smoke/cold_start_android.json")
        self.assertEqual(scenario.platform, "android")
        self.assertGreaterEqual(len(scenario.steps), 1)

    def test_tap_requires_selector_target_or_coordinates(self) -> None:
        scenario = self._scenario_with_steps([{"action": "tap"}])
        with self.assertRaisesRegex(ValueError, "tap requires selector"):
            self._load_from_payload(scenario)

    def test_tap_accepts_coordinates(self) -> None:
        scenario = self._scenario_with_steps([{"action": "tap", "x": 12, "y": 34}])
        self._load_from_payload(scenario)

    def test_tap_rejects_partial_or_non_int_coordinates(self) -> None:
        scenario = self._scenario_with_steps([{"action": "tap", "x": 12}])
        with self.assertRaisesRegex(ValueError, "tap requires integer x and y"):
            self._load_from_payload(scenario)
        scenario = self._scenario_with_steps([{"action": "tap", "x": "12", "y": 34}])
        with self.assertRaisesRegex(ValueError, "tap requires integer x and y"):
            self._load_from_payload(scenario)

    def test_tap_accepts_selector_or_target(self) -> None:
        scenario = self._scenario_with_steps(
            [
                {
                    "action": "tap",
                    "selector": {"by": "id", "value": "login_button"},
                }
            ]
        )
        self._load_from_payload(scenario)
        scenario = self._scenario_with_steps([{"action": "tap", "target": "login_button"}])
        self._load_from_payload(scenario)

    def test_input_text_requires_selector_or_target(self) -> None:
        scenario = self._scenario_with_steps([{"action": "input_text", "text": "hi"}])
        with self.assertRaisesRegex(ValueError, "input_text requires selector .* target"):
            self._load_from_payload(scenario)
        scenario = self._scenario_with_steps(
            [{"action": "input_text", "text": "hi", "selector": {"by": "id", "value": "field"}}]
        )
        self._load_from_payload(scenario)
        scenario = self._scenario_with_steps([{"action": "input_text", "text": "hi", "target": "field"}])
        self._load_from_payload(scenario)

    def test_assertions_require_selector_or_target(self) -> None:
        for action in ("assert_visible", "assert_eventually", "expect_transition"):
            scenario = self._scenario_with_steps([{"action": action}])
            with self.assertRaisesRegex(ValueError, f"{action} requires selector .* target"):
                self._load_from_payload(scenario)
            scenario = self._scenario_with_steps([{"action": action, "target": "home_screen"}])
            self._load_from_payload(scenario)

    def test_selector_must_have_by_and_value(self) -> None:
        scenario = self._scenario_with_steps([{"action": "tap", "selector": {"by": "id"}}])
        with self.assertRaisesRegex(ValueError, "selector must be a dict with 'by' and 'value'"):
            self._load_from_payload(scenario)
        scenario = self._scenario_with_steps([{"action": "input_text", "selector": "id=field"}])
        with self.assertRaisesRegex(ValueError, "selector must be a dict with 'by' and 'value'"):
            self._load_from_payload(scenario)

    def _scenario_with_steps(self, steps: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "name": "test-scenario",
            "platform": "android",
            "app": {"android_package": "com.example.app"},
            "steps": steps,
        }

    def _load_from_payload(self, payload: dict[str, Any]) -> None:
        handle, path = tempfile.mkstemp(suffix=".json")
        os.close(handle)
        try:
            with open(path, "w", encoding="utf-8") as temp_file:
                json.dump(payload, temp_file)
            load_scenario(path)
        finally:
            os.remove(path)


if __name__ == "__main__":
    unittest.main()
