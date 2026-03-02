from __future__ import annotations

import hashlib
from typing import Any


def build_ref(platform: str, node: dict[str, Any]) -> str:
    material = "|".join(
        [
            platform,
            str(node.get("id", "")),
            str(node.get("label", "")),
            str(node.get("type", "")),
            str(node.get("path", "")),
            str(node.get("ordinal", "")),
        ]
    )
    digest = hashlib.sha1(material.encode("utf-8")).hexdigest()[:10]
    return f"@e{digest}"


def build_anchor(node: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": node.get("id"),
        "label": node.get("label"),
        "type": node.get("type"),
        "text": node.get("text"),
        "path": node.get("path"),
        "resource_id": node.get("resource_id"),
        "class_name": node.get("class_name"),
        "content_desc": node.get("content_desc"),
        "bounds": node.get("bounds"),
    }


def make_selector(by: str, value: str, within: str | None = None, platform_hint: str | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {"by": by, "value": value}
    if within:
        payload["within"] = within
    if platform_hint:
        payload["platform_hint"] = platform_hint
    return payload


def _anchor_score(anchor: dict[str, Any], node: dict[str, Any]) -> float:
    score = 0.0
    if anchor.get("id") and anchor.get("id") == node.get("id"):
        score += 0.3
    if anchor.get("resource_id") and anchor.get("resource_id") == node.get("resource_id"):
        score += 0.25
    if anchor.get("label") and anchor.get("label") == node.get("label"):
        score += 0.15
    if anchor.get("type") and anchor.get("type") == node.get("type"):
        score += 0.1
    if anchor.get("class_name") and anchor.get("class_name") == node.get("class_name"):
        score += 0.1
    if anchor.get("content_desc") and anchor.get("content_desc") == node.get("content_desc"):
        score += 0.05
    if anchor.get("text") and anchor.get("text") == node.get("text"):
        score += 0.03
    if anchor.get("path") and anchor.get("path") == node.get("path"):
        score += 0.01
    if anchor.get("bounds") and anchor.get("bounds") == node.get("bounds"):
        score += 0.01
    return score


def resolve_selector(
    selector: dict[str, Any],
    elements: list[dict[str, Any]],
    *,
    score_threshold: float = 0.75,
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    by = selector.get("by")
    value = str(selector.get("value", ""))
    candidates: list[dict[str, Any]]
    confidence = 1.0

    if by == "ref":
        exact = [el for el in elements if el.get("ref") == value]
        if exact:
            return exact[0], {"candidate_count": 1, "confidence": 1.0, "match_type": "exact_ref"}

        anchor = selector.get("anchor")
        if not isinstance(anchor, dict):
            return None, {"candidate_count": 0, "confidence": 0.0, "match_type": "drift"}

        scored = [(el, _anchor_score(anchor, el)) for el in elements]
        scored.sort(key=lambda item: item[1], reverse=True)
        best, score = scored[0]
        if score >= score_threshold:
            return best, {"candidate_count": len(scored), "confidence": score, "match_type": "anchor"}
        return None, {"candidate_count": len(scored), "confidence": score, "match_type": "drift"}

    if by == "id":
        candidates = [el for el in elements if str(el.get("id", "")) == value]
    elif by == "resource_id":
        candidates = [el for el in elements if str(el.get("resource_id", "")) == value]
    elif by == "content_desc":
        candidates = [el for el in elements if str(el.get("content_desc", "")) == value]
    elif by == "class_name":
        candidates = [el for el in elements if str(el.get("class_name", "")) == value]
    elif by == "label":
        candidates = [el for el in elements if str(el.get("label", "")) == value]
    elif by == "text":
        candidates = [el for el in elements if str(el.get("text", "")) == value]
    elif by == "type":
        candidates = [el for el in elements if str(el.get("type", "")) == value]
    else:
        return None, {"candidate_count": 0, "confidence": 0.0, "match_type": "unsupported"}

    if not candidates:
        return None, {"candidate_count": 0, "confidence": 0.0, "match_type": "not_found"}

    candidates.sort(key=lambda item: str(item.get("path", "")))
    if len(candidates) > 1:
        confidence = 0.85
    return candidates[0], {"candidate_count": len(candidates), "confidence": confidence, "match_type": by}
