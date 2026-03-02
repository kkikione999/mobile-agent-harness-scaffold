from __future__ import annotations

import unittest

from harness.driver.dsl import load_scenario


class TestDSL(unittest.TestCase):
    def test_load_android_smoke(self) -> None:
        scenario = load_scenario("scenarios/smoke/cold_start_android.json")
        self.assertEqual(scenario.platform, "android")
        self.assertGreaterEqual(len(scenario.steps), 1)


if __name__ == "__main__":
    unittest.main()
