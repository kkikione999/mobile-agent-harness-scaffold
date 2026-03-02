from __future__ import annotations

import unittest

from harness.driver.selectors import resolve_selector


class TestSelectors(unittest.TestCase):
    def test_ref_anchor_fallback(self) -> None:
        elements = [
            {
                "ref": "@e123",
                "id": "home_screen",
                "label": "Home Screen",
                "type": "view",
                "text": "",
                "path": "0/1",
            }
        ]
        selector = {
            "by": "ref",
            "value": "@emissing",
            "anchor": {
                "id": "home_screen",
                "label": "Home Screen",
                "type": "view",
                "text": "",
                "path": "0/1",
            },
        }

        matched, info = resolve_selector(selector, elements)
        self.assertIsNotNone(matched)
        self.assertEqual(info["match_type"], "anchor")
        self.assertGreaterEqual(info["confidence"], 0.75)


if __name__ == "__main__":
    unittest.main()
