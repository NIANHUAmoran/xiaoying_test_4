"""Deterministic, inspectable tools for a deliberately constrained script demo.

Grounding is exact phrase validation against retrieved source facts and an
explicit neutral phrase library. It is not general natural-language entailment.
"""

from __future__ import annotations

from copy import deepcopy
import re
import unicodedata
from typing import Any


_SCRIPT_KEYS = {"title", "scenes"}
_SCENE_KEYS = {
    "id", "visual", "narration", "subtitle", "duration_seconds", "source_refs"
}
_REFERENCE_KEYS = {"material_id", "fact_id", "quote"}
_MATERIAL_KEYS = {"id", "title", "keywords", "facts"}
_FACT_KEYS = {"id", "text"}
_BRAND_KEYS = {
    "approved_titles", "approved_visuals", "neutral_phrases", "forbidden_phrases"
}
_SENTENCE_BREAK = re.compile(r"[。！？；!?;\r\n]+")
_TRAILING_PUNCTUATION = "。！？；!?;.,，:：、"


def _nonempty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _positive_integer(value: Any) -> bool:
    # bool is an int subclass, but is not a duration or a configuration value.
    return type(value) is int and value > 0


def _phrase(value: str) -> str:
    """Remove whitespace and terminal punctuation without paraphrasing text."""
    return "".join(value.split()).rstrip(_TRAILING_PUNCTUATION)


def _sentences(value: str) -> list[str]:
    return [phrase for item in _SENTENCE_BREAK.split(value) if (phrase := _phrase(item))]


def _effective_characters(value: str) -> int:
    return sum(
        1 for character in value
        if not character.isspace() and not unicodedata.category(character).startswith("P")
    )


def _validate_string_list(value: Any, label: str, *, allow_empty: bool = False) -> None:
    if not isinstance(value, list) or (not value and not allow_empty):
        raise ValueError(f"{label} must be a nonempty list")
    if any(not _nonempty_string(item) for item in value):
        raise ValueError(f"{label} must contain nonempty strings")
    if len(set(value)) != len(value):
        raise ValueError(f"{label} must not contain duplicates")


class ScriptTools:
    """Local material search, heuristic timing, and exact grounding checks.

    The constructor copies the validated world. Search outputs are copied too,
    so a consumer cannot mutate the corpus through a returned tool result.
    Fault injection and tool-call/revision limits belong to the agent runtime.
    """

    def __init__(self, world: dict[str, Any]):
        self._validate_world(world)
        self._world = deepcopy(world)
        self._world["brand"].setdefault("max_scenes", 6)
        self._materials = {item["id"]: item for item in self._world["materials"]}

    @staticmethod
    def _validate_world(world: Any) -> None:
        required = {"materials", "brand", "timing", "failures"}
        if not isinstance(world, dict) or set(world) != required:
            raise ValueError("world must contain materials, brand, timing and failures")
        if not isinstance(world["materials"], list):
            raise ValueError("world materials must be a list")
        material_ids: set[str] = set()
        for material in world["materials"]:
            if not isinstance(material, dict) or set(material) != _MATERIAL_KEYS:
                raise ValueError("material fields are invalid")
            if not _nonempty_string(material["id"]) or not _nonempty_string(material["title"]):
                raise ValueError("material id and title must be nonempty strings")
            if material["id"] in material_ids:
                raise ValueError("material ids must be unique")
            material_ids.add(material["id"])
            _validate_string_list(material["keywords"], "material keywords")
            if not isinstance(material["facts"], list) or not material["facts"]:
                raise ValueError("material facts must be a nonempty list")
            fact_ids: set[str] = set()
            for fact in material["facts"]:
                if not isinstance(fact, dict) or set(fact) != _FACT_KEYS:
                    raise ValueError("fact fields are invalid")
                if not _nonempty_string(fact["id"]) or not _nonempty_string(fact["text"]):
                    raise ValueError("fact id and text must be nonempty strings")
                if not _phrase(fact["text"]):
                    raise ValueError("fact text must contain content")
                if fact["id"] in fact_ids:
                    raise ValueError("fact ids must be unique within each material")
                fact_ids.add(fact["id"])
        brand = world["brand"]
        if not isinstance(brand, dict) or not _BRAND_KEYS.issubset(brand):
            raise ValueError("brand fields are invalid")
        if set(brand) - (_BRAND_KEYS | {"max_scenes"}):
            raise ValueError("brand contains unknown fields")
        for field in sorted(_BRAND_KEYS):
            _validate_string_list(brand[field], f"brand {field}")
            if any(not _phrase(item) for item in brand[field]):
                raise ValueError("brand phrases must contain content")
        if not _positive_integer(brand.get("max_scenes", 6)):
            raise ValueError("brand max_scenes must be a positive integer")
        timing = world["timing"]
        if not isinstance(timing, dict) or set(timing) != {
            "characters_per_second", "minimum_scene_seconds"
        }:
            raise ValueError("timing fields are invalid")
        if any(not _positive_integer(value) for value in timing.values()):
            raise ValueError("timing values must be positive integers")
        failures = world["failures"]
        if not isinstance(failures, list):
            raise ValueError("failures must be a list")
        failure_tools: set[str] = set()
        for failure in failures:
            if not isinstance(failure, dict) or set(failure) != {"tool", "mode"}:
                raise ValueError("failure fields are invalid")
            if (not _nonempty_string(failure["tool"])
                    or not isinstance(failure["mode"], str)
                    or failure["mode"] not in {"once", "always"}):
                raise ValueError("failure tool or mode is invalid")
            if failure["tool"] in failure_tools:
                raise ValueError("failure tools must be unique")
            failure_tools.add(failure["tool"])

    @staticmethod
    def validate_script(script: Any) -> None:
        """Validate structure only; grounding errors are repairable check issues."""
        if not isinstance(script, dict) or set(script) != _SCRIPT_KEYS:
            raise ValueError("script must contain exactly title and scenes")
        if not _nonempty_string(script["title"]):
            raise ValueError("script title must be a nonempty string")
        if not isinstance(script["scenes"], list) or not script["scenes"]:
            raise ValueError("script scenes must be a nonempty list")
        scene_ids: set[str] = set()
        for scene in script["scenes"]:
            if not isinstance(scene, dict) or set(scene) != _SCENE_KEYS:
                raise ValueError("scene fields are invalid")
            if not _nonempty_string(scene["id"]) or scene["id"] in scene_ids:
                raise ValueError("scene ids must be nonempty and unique")
            scene_ids.add(scene["id"])
            if not _nonempty_string(scene["visual"]):
                raise ValueError("scene visual must be a nonempty string")
            if not isinstance(scene["narration"], str) or not isinstance(scene["subtitle"], str):
                raise ValueError("scene narration and subtitle must be strings")
            if not _effective_characters(scene["narration"] + scene["subtitle"]):
                raise ValueError("scene must contain narration or subtitle content")
            if not _positive_integer(scene["duration_seconds"]):
                raise ValueError("scene duration_seconds must be a positive integer")
            if not isinstance(scene["source_refs"], list):
                raise ValueError("scene source_refs must be a list")
            reference_ids: set[tuple[str, str]] = set()
            for reference in scene["source_refs"]:
                if not isinstance(reference, dict) or set(reference) != _REFERENCE_KEYS:
                    raise ValueError("source reference fields are invalid")
                if any(not _nonempty_string(value) for value in reference.values()):
                    raise ValueError("source reference values must be nonempty strings")
                key = (reference["material_id"], reference["fact_id"])
                if key in reference_ids:
                    raise ValueError("source references must be unique within each scene")
                reference_ids.add(key)

    def search(self, query: str) -> dict[str, Any]:
        """Match literal keywords; no semantic search or invented fallback facts."""
        if not _nonempty_string(query):
            raise ValueError("search query must be a nonempty string")
        normalized_query = "".join(query.split()).casefold()
        found = []
        for material in self._world["materials"]:
            if any("".join(keyword.split()).casefold() in normalized_query for keyword in material["keywords"]):
                found.append(deepcopy(material))
        return {"ok": True, "materials": found}

    def estimate(self, script: dict[str, Any], target_seconds: int) -> dict[str, Any]:
        self.validate_script(script)
        if not _positive_integer(target_seconds):
            raise ValueError("target_seconds must be a positive integer")
        timing = self._world["timing"]
        characters_per_second = timing["characters_per_second"]
        scene_estimates = []
        for scene in script["scenes"]:
            # Integer ceiling avoids float precision/overflow for numeric inputs.
            speech_seconds = (
                _effective_characters(scene["narration"]) + characters_per_second - 1
            ) // characters_per_second
            subtitle_seconds = (
                _effective_characters(scene["subtitle"]) + characters_per_second - 1
            ) // characters_per_second
            estimated_seconds = max(
                scene["duration_seconds"], speech_seconds, subtitle_seconds,
                timing["minimum_scene_seconds"]
            )
            scene_estimates.append({
                "scene_id": scene["id"],
                "estimated_seconds": estimated_seconds,
                "speech_seconds": speech_seconds,
                "subtitle_seconds": subtitle_seconds,
                "requested_seconds": scene["duration_seconds"],
            })
        total_seconds = sum(item["estimated_seconds"] for item in scene_estimates)
        return {
            "ok": True,
            "total_seconds": total_seconds,
            "within_limit": total_seconds <= target_seconds,
            "over_seconds": max(0, total_seconds - target_seconds),
            "scene_estimates": scene_estimates,
        }

    def check(self, script: dict[str, Any], retrieved: dict[str, Any]) -> dict[str, Any]:
        self.validate_script(script)
        if not isinstance(retrieved, dict):
            raise ValueError("retrieved materials must be a dictionary")
        brand = self._world["brand"]
        issues: list[dict[str, str]] = []
        verified_sources: list[dict[str, str]] = []
        verified_ids: set[tuple[str, str, str]] = set()

        def issue(code: str, detail: str, scene_id: str | None = None) -> None:
            item = {"code": code, "detail": detail}
            if scene_id is not None:
                item["scene_id"] = scene_id
            if item not in issues:
                issues.append(item)

        def check_forbidden(text: str, location: str, scene_id: str | None = None) -> None:
            normalized = _phrase(text).casefold()
            if any(_phrase(phrase).casefold() in normalized for phrase in brand["forbidden_phrases"]):
                issue("forbidden_phrase", f"{location} contains a brand-forbidden phrase", scene_id)

        if script["title"] not in brand["approved_titles"]:
            issue("title_not_approved", "title must use an approved option")
        check_forbidden(script["title"], "title")
        if len(script["scenes"]) > brand["max_scenes"]:
            issue("scene_count_exceeded", "scene count exceeds the configured brand limit")
        neutral = {_phrase(phrase) for phrase in brand["neutral_phrases"]}

        for scene in script["scenes"]:
            scene_id = scene["id"]
            if scene["visual"] not in brand["approved_visuals"]:
                issue("visual_not_approved", "visual must use an approved option", scene_id)
            for field in ("visual", "narration", "subtitle"):
                check_forbidden(scene[field], field, scene_id)
            sentences = _sentences(scene["narration"]) + _sentences(scene["subtitle"])
            local_facts: set[str] = set()
            for reference in scene["source_refs"]:
                material_id, fact_id = reference["material_id"], reference["fact_id"]
                if material_id not in retrieved:
                    issue("material_not_retrieved", "source material was not retrieved", scene_id)
                    continue
                trusted_material = self._materials.get(material_id)
                if trusted_material is None or retrieved[material_id] != trusted_material:
                    issue("material_content_mismatch", "retrieved source differs from the corpus", scene_id)
                    continue
                fact = next((item for item in trusted_material["facts"] if item["id"] == fact_id), None)
                if fact is None:
                    issue("unknown_fact", "source fact id does not exist", scene_id)
                    continue
                if reference["quote"] != fact["text"]:
                    issue("quote_mismatch", "source quote must equal the full fact text", scene_id)
                    continue
                normalized_fact = _phrase(fact["text"])
                if normalized_fact not in sentences:
                    issue("unused_reference", "cited fact must appear in this scene", scene_id)
                    continue
                local_facts.add(normalized_fact)
                key = (material_id, fact_id, fact["text"])
                if key not in verified_ids:
                    verified_ids.add(key)
                    verified_sources.append({
                        "material_id": material_id, "fact_id": fact_id, "quote": fact["text"]
                    })
            # A source fact appearing without this scene's reference must not be
            # accepted merely because a different scene carries the annotation.
            retrieved_facts = {
                _phrase(fact["text"])
                for material_id, material in self._materials.items()
                if retrieved.get(material_id) == material
                for fact in material["facts"]
            }
            for sentence in sentences:
                if sentence in local_facts:
                    continue
                if sentence in retrieved_facts:
                    issue("missing_source_reference", "fact requires a source reference on this scene", scene_id)
                elif sentence not in neutral:
                    issue("unsupported_text", "text must equal a cited fact or an allowed neutral phrase", scene_id)
        if not verified_sources:
            issue("no_product_evidence", "script must contain at least one verified product fact")
        return {
            "ok": True,
            "passed": not issues,
            "issues": issues,
            "verified_sources": verified_sources,
        }
