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
                "resource_id": "home_screen",
                "class_name": "android.view.View",
                "content_desc": "home screen",
                "bounds": [0, 0, 100, 100],
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
                "resource_id": "home_screen",
                "class_name": "android.view.View",
                "content_desc": "home screen",
                "bounds": [0, 0, 100, 100],
            },
        }

        matched, info = resolve_selector(selector, elements)
        self.assertIsNotNone(matched)
        self.assertEqual(info["match_type"], "anchor")
        self.assertGreaterEqual(info["confidence"], 0.75)

    def test_resource_id_selector(self) -> None:
        elements = [
            {
                "ref": "@eaaa",
                "id": "root",
                "resource_id": "com.example:id/root",
                "label": "Root",
                "type": "android.view.View",
                "path": "0",
            }
        ]
        matched, info = resolve_selector({"by": "resource_id", "value": "com.example:id/root"}, elements)
        self.assertIsNotNone(matched)
        self.assertEqual(info["match_type"], "resource_id")


if __name__ == "__main__":
    unittest.main()
