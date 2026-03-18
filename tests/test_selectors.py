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

    def test_within_scopes_candidates(self) -> None:
        elements = [
            {"ref": "@e0", "id": "root", "path": "0"},
            {"ref": "@e1", "id": "panel_a", "path": "0/1"},
            {"ref": "@e2", "id": "panel_b", "path": "0/2"},
            {"ref": "@e3", "id": "button", "label": "Submit", "path": "0/1/0"},
            {"ref": "@e4", "id": "button", "label": "Submit", "path": "0/2/0"},
        ]

        selector = {"by": "id", "value": "button", "within": "@e2"}
        matched, info = resolve_selector(selector, elements)
        self.assertIsNotNone(matched)
        self.assertEqual(matched["ref"], "@e4")
        self.assertEqual(info["candidate_count"], 1)
        self.assertEqual(info["match_type"], "id")

    def test_within_unresolved_returns_not_found(self) -> None:
        elements = [
            {"ref": "@e0", "id": "root", "path": "0"},
            {"ref": "@e1", "id": "panel_a", "path": "0/1"},
            {"ref": "@e2", "id": "button", "path": "0/1/0"},
        ]

        selector = {"by": "id", "value": "button", "within": "missing_panel"}
        matched, info = resolve_selector(selector, elements)
        self.assertIsNone(matched)
        self.assertEqual(info["match_type"], "not_found")
        self.assertEqual(info["candidate_count"], 0)

    def test_id_selector_orders_by_path(self) -> None:
        elements = [
            {"ref": "@e1", "id": "dup", "path": "0/2"},
            {"ref": "@e2", "id": "dup", "path": "0/1"},
        ]

        matched, info = resolve_selector({"by": "id", "value": "dup"}, elements)
        self.assertIsNotNone(matched)
        self.assertEqual(matched["ref"], "@e2")
        self.assertEqual(info["candidate_count"], 2)
        self.assertEqual(info["confidence"], 0.85)

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

    def test_semantic_id_selector_prefers_exact_app_semantics(self) -> None:
        elements = [
            {
                "ref": "@e111",
                "id": "legacy_row",
                "label": "settings.sign_out_tile",
                "text": "settings.sign_out_tile",
                "path": "0/2",
            },
            {
                "ref": "@e222",
                "id": "settings_sign_out_tile",
                "semantic_id": "settings.sign_out_tile",
                "label": "Sign out",
                "text": "Sign out",
                "path": "0/1",
            },
        ]

        matched, info = resolve_selector({"by": "semantic_id", "value": "settings.sign_out_tile"}, elements)
        self.assertIsNotNone(matched)
        self.assertEqual(matched["ref"], "@e222")
        self.assertEqual(info["match_type"], "semantic_id")
        self.assertEqual(info["candidate_count"], 1)
        self.assertEqual(info["confidence"], 1.0)

    def test_semantic_id_selector_orders_ambiguous_matches_by_path(self) -> None:
        elements = [
            {
                "ref": "@e111",
                "id": "settings_sign_out_tile_primary",
                "semantic_id": "settings.sign_out_tile",
                "path": "0/2",
            },
            {
                "ref": "@e222",
                "id": "settings_sign_out_tile_secondary",
                "semantic_id": "settings.sign_out_tile",
                "path": "0/1",
            },
        ]

        matched, info = resolve_selector({"by": "semantic_id", "value": "settings.sign_out_tile"}, elements)
        self.assertIsNotNone(matched)
        self.assertEqual(matched["ref"], "@e222")
        self.assertEqual(info["match_type"], "semantic_id")
        self.assertEqual(info["candidate_count"], 2)
        self.assertEqual(info["confidence"], 0.85)

    def test_semantic_id_selector_falls_back_to_legacy_id(self) -> None:
        elements = [
            {
                "ref": "@e111",
                "id": "settings_sign_out_tile",
                "label": "Sign out",
                "path": "0/1",
            }
        ]

        matched, info = resolve_selector({"by": "semantic_id", "value": "settings.sign_out_tile"}, elements)
        self.assertIsNotNone(matched)
        self.assertEqual(matched["ref"], "@e111")
        self.assertEqual(info["match_type"], "semantic_id_fallback")
        self.assertEqual(info["fallback_field"], "id")
        self.assertEqual(info["candidate_count"], 1)

    def test_id_selector_can_fail_closed_on_ambiguity(self) -> None:
        elements = [
            {"ref": "@e1", "id": "dup", "label": "Save", "path": "0/2"},
            {"ref": "@e2", "id": "dup", "label": "Save", "path": "0/1"},
        ]

        matched, info = resolve_selector(
            {"by": "id", "value": "dup", "ambiguity_mode": "error", "candidate_limit": 2},
            elements,
        )
        self.assertIsNone(matched)
        self.assertEqual(info["match_type"], "ambiguous")
        self.assertEqual(info["candidate_count"], 2)
        self.assertEqual([item["ref"] for item in info["candidates"]], ["@e2", "@e1"])

    def test_within_can_fail_closed_on_ambiguous_container(self) -> None:
        elements = [
            {"ref": "@e0", "id": "root", "path": "0"},
            {"ref": "@e1", "id": "panel", "path": "0/1"},
            {"ref": "@e2", "id": "panel", "path": "0/2"},
            {"ref": "@e3", "id": "button", "label": "Submit", "path": "0/1/0"},
            {"ref": "@e4", "id": "button", "label": "Submit", "path": "0/2/0"},
        ]

        matched, info = resolve_selector(
            {"by": "id", "value": "button", "within": "panel", "ambiguity_mode": "error"},
            elements,
        )
        self.assertIsNone(matched)
        self.assertEqual(info["match_type"], "ambiguous_within")
        self.assertEqual(info["candidate_count"], 2)

    def test_anchor_tie_can_fail_closed(self) -> None:
        elements = [
            {
                "ref": "@e1",
                "id": "save_primary",
                "label": "Save",
                "type": "button",
                "text": "Save",
                "path": "0/1",
                "resource_id": "save_primary",
                "class_name": "android.widget.Button",
                "content_desc": "save",
                "bounds": [0, 0, 50, 20],
            },
            {
                "ref": "@e2",
                "id": "save_secondary",
                "label": "Save",
                "type": "button",
                "text": "Save",
                "path": "0/2",
                "resource_id": "save_secondary",
                "class_name": "android.widget.Button",
                "content_desc": "save",
                "bounds": [60, 0, 110, 20],
            },
        ]
        selector = {
            "by": "ref",
            "value": "@emissing",
            "ambiguity_mode": "error",
            "anchor": {
                "label": "Save",
                "type": "button",
                "text": "Save",
                "class_name": "android.widget.Button",
                "content_desc": "save",
            },
        }

        matched, info = resolve_selector(selector, elements, score_threshold=0.4)
        self.assertIsNone(matched)
        self.assertEqual(info["match_type"], "ambiguous")
        self.assertEqual(info["candidate_count"], 2)


if __name__ == "__main__":
    unittest.main()
