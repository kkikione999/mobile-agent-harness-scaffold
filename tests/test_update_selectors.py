from __future__ import annotations

import unittest

from tools.update_selectors import _update_steps


class TestUpdateSelectors(unittest.TestCase):
    def test_coordinate_tap_resolves_smallest_bounds(self) -> None:
        steps = [{"action": "tap", "x": 20, "y": 20}]
        elements = [
            {
                "ref": "@e_big",
                "bounds": [0, 0, 100, 100],
                "anchor": {"id": "big"},
                "path": "0/1",
            },
            {
                "ref": "@e_small",
                "bounds": [10, 10, 50, 50],
                "anchor": {"id": "small"},
                "path": "0/2",
            },
        ]

        updated_steps, updates = _update_steps(steps, elements)

        self.assertEqual(len(updated_steps), 1)
        updated_step = updated_steps[0]
        self.assertNotIn("x", updated_step)
        self.assertNotIn("y", updated_step)
        self.assertEqual(updated_step["selector"]["by"], "ref")
        self.assertEqual(updated_step["selector"]["value"], "@e_small")
        self.assertEqual(updated_step["selector"]["anchor"], {"id": "small"})

        self.assertEqual(len(updates), 1)
        self.assertEqual(updates[0]["status"], "updated")
        self.assertEqual(updates[0]["matched_ref"], "@e_small")

    def test_coordinate_tap_unresolved(self) -> None:
        steps = [{"action": "tap", "x": 200, "y": 200}]
        elements = [
            {
                "ref": "@e_only",
                "bounds": [0, 0, 50, 50],
                "anchor": {"id": "only"},
                "path": "0/1",
            }
        ]

        updated_steps, updates = _update_steps(steps, elements)

        self.assertEqual(len(updated_steps), 1)
        self.assertEqual(updated_steps[0], steps[0])
        self.assertEqual(len(updates), 1)
        self.assertEqual(updates[0]["status"], "unresolved")
        self.assertIsNone(updates[0]["matched_ref"])


if __name__ == "__main__":
    unittest.main()
