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
        "semantic_id": node.get("semantic_id"),
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
    if anchor.get("semantic_id") and anchor.get("semantic_id") == node.get("semantic_id"):
        score += 0.35
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


def _semantic_id_variants(value: str) -> tuple[str, ...]:
    variants = [value]
    underscored = value.replace(".", "_")
    dashed = value.replace(".", "-")
    for candidate in (underscored, dashed):
        if candidate and candidate not in variants:
            variants.append(candidate)
    return tuple(variants)


def _sorted_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(candidates, key=lambda item: (str(item.get("path", "")), str(item.get("ref", ""))))


def _resolved_match(
    candidates: list[dict[str, Any]],
    *,
    match_type: str,
    confidence: float = 1.0,
) -> tuple[dict[str, Any], dict[str, Any]]:
    ordered = _sorted_candidates(candidates)
    resolved = ordered[0]
    resolved_confidence = confidence if len(ordered) == 1 else min(confidence, 0.85)
    return resolved, {
        "candidate_count": len(ordered),
        "confidence": resolved_confidence,
        "match_type": match_type,
    }


def _semantic_id_fallback(
    value: str,
    elements: list[dict[str, Any]],
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    variants = _semantic_id_variants(value)
    fallback_candidates: list[tuple[float, str, dict[str, Any]]] = []

    for element in elements:
        element_id = str(element.get("id", ""))
        resource_id = str(element.get("resource_id", ""))
        if element_id in variants:
            fallback_candidates.append((0.95, "id", element))
        if resource_id in variants:
            fallback_candidates.append((0.92, "resource_id", element))
        elif any(resource_id.endswith(f"/{variant}") or resource_id.endswith(f":{variant}") for variant in variants):
            fallback_candidates.append((0.9, "resource_id", element))

        for field_name, score in (("label", 0.72), ("text", 0.7), ("content_desc", 0.68)):
            if str(element.get(field_name, "")) == value:
                fallback_candidates.append((score, field_name, element))

    if not fallback_candidates:
        return None, None

    fallback_candidates.sort(
        key=lambda item: (
            -item[0],
            str(item[2].get("path", "")),
            str(item[2].get("ref", "")),
        )
    )
    best_score, best_field, _ = fallback_candidates[0]
    best_candidates = [
        element
        for score, field_name, element in fallback_candidates
        if score == best_score and field_name == best_field
    ]
    resolved, info = _resolved_match(
        best_candidates,
        match_type="semantic_id_fallback",
        confidence=best_score,
    )
    info["fallback_field"] = best_field
    return resolved, info


def _scope_elements_within(
    selector: dict[str, Any],
    elements: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    within = selector.get("within")
    if not within:
        return elements, None

    within_value = str(within)
    if within_value.startswith("@e"):
        within_element = next((el for el in elements if el.get("ref") == within_value), None)
    else:
        within_element = next((el for el in elements if str(el.get("id", "")) == within_value), None)

    if not within_element:
        return [], {"candidate_count": 0, "confidence": 0.0, "match_type": "not_found"}

    within_path = str(within_element.get("path", ""))
    if not within_path:
        return [], {"candidate_count": 0, "confidence": 0.0, "match_type": "not_found"}

    prefix = f"{within_path}/"
    scoped = [el for el in elements if str(el.get("path", "")).startswith(prefix)]
    return scoped, None


def resolve_selector(
    selector: dict[str, Any],
    elements: list[dict[str, Any]],
    *,
    score_threshold: float = 0.75,
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    elements, scope_info = _scope_elements_within(selector, elements)
    if scope_info is not None:
        return None, scope_info
    if selector.get("within") and not elements:
        return None, {"candidate_count": 0, "confidence": 0.0, "match_type": "not_found"}

    by = selector.get("by")
    value = str(selector.get("value", ""))
    candidates: list[dict[str, Any]]
    confidence = 1.0

    if by == "ref":
        exact = [el for el in elements if el.get("ref") == value]
        if exact:
            return _resolved_match(exact, match_type="exact_ref")

        anchor = selector.get("anchor")
        if not isinstance(anchor, dict):
            return None, {"candidate_count": 0, "confidence": 0.0, "match_type": "drift"}

        scored = [(el, _anchor_score(anchor, el)) for el in elements]
        scored.sort(key=lambda item: item[1], reverse=True)
        best, score = scored[0]
        if score >= score_threshold:
            return best, {"candidate_count": len(scored), "confidence": score, "match_type": "anchor"}
        return None, {"candidate_count": len(scored), "confidence": score, "match_type": "drift"}

    if by == "semantic_id":
        candidates = [el for el in elements if str(el.get("semantic_id", "")) == value]
        if candidates:
            return _resolved_match(candidates, match_type="semantic_id")

        fallback_match, fallback_info = _semantic_id_fallback(value, elements)
        if fallback_match is not None and fallback_info is not None:
            return fallback_match, fallback_info
        return None, {"candidate_count": 0, "confidence": 0.0, "match_type": "not_found"}

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

    return _resolved_match(candidates, match_type=str(by), confidence=confidence)
