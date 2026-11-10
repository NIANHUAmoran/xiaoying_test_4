"""Executable acceptance and adversarial tests for the short-video script agent.

The deterministic model proves orchestration behavior, not a real model's quality.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
import unittest

from src.agent import run
from src.models import MockModel
from src.tools import ScriptTools


ROOT = Path(__file__).resolve().parents[1]


def request(**changes):
    value = {
        "theme": "字幕介绍",
        "audience": "新手创作者",
        "platform": "短视频",
        "target_seconds": 45,
        "style": "简洁",
    }
    value.update(changes)
    return value


def world(filename="world.json"):
    return json.loads((ROOT / "data" / filename).read_text(encoding="utf-8"))


def draft():
    return {
        "title": "字幕功能展示",
        "scenes": [
            {
                "id": "S1",
                "visual": "展示带字幕的示意画面",
                "narration": "支持字幕。",
                "subtitle": "支持字幕。",
                "duration_seconds": 20,
                "source_refs": [
                    {"material_id": "P01", "fact_id": "F1", "quote": "支持字幕"}
                ],
            },
            {
                "id": "S2",
                "visual": "切换到片尾文字卡",
                "narration": "试着制作你的下一条视频。",
                "subtitle": "试着制作你的下一条视频。",
                "duration_seconds": 18,
                "source_refs": [],
            },
        ],
    }


def action(name, arguments=None):
    return {
        "action": name,
        "arguments": arguments or {},
        "basis": "根据当前工具返回选择下一步。",
    }


class ScriptModel:
    """A deliberate action sequence used to probe the runtime's trust boundary."""

    mode = "mock"
    name = "scripted-test-double"

    def __init__(self, actions):
        self.actions = iter(actions)

    def decide(self, *args, **kwargs):
        return copy.deepcopy(next(self.actions))


class ScriptAgentTests(unittest.TestCase):
    def run_mock(self, req=None, fixture="world.json", **kwargs):
        return run(req or request(), world(fixture), MockModel(), **kwargs)

    def assert_not_exported(self, result):
        self.assertNotEqual("completed", result["status"])
        self.assertIsNone(result["script"])
        self.assertFalse(result.get("scenes"))
        self.assertFalse(result.get("source_ids"))

    def assert_checked(self, result, expected_seconds):
        self.assertEqual("completed", result["status"])
        self.assertTrue(result["checks"]["estimate_duration"]["within_limit"])
        self.assertTrue(result["checks"]["check_rules"]["passed"])
        self.assertEqual(expected_seconds, result["estimated_total_seconds"])
        latest = result["revisions"][-1]["revision"]
        for check in result["checks"].values():
            self.assertEqual(latest, check["revision"])

    def sequence(self, actions):
        return run(request(), world(), ScriptModel(actions))

    def checked_actions(self, script=None):
        return [
            action("search_materials", {"query": "字幕"}),
            action("write_script", {"script": script or draft()}),
            action("estimate_duration"),
            action("check_rules"),
        ]

    def test_01_normal_generation_exports_checked_script_and_sources(self):
        result = self.run_mock()
        self.assert_checked(result, 38)
        self.assertEqual("字幕功能展示", result["script"]["title"])
        self.assertEqual(["P01"], result["source_ids"])
        self.assertEqual(2, len(result["script"]["scenes"]))
        self.assertEqual("P01", result["script"]["scenes"][0]["source_refs"][0]["material_id"])
        estimates = result["checks"]["estimate_duration"]["scene_estimates"]
        for scene, estimate in zip(result["script"]["scenes"], estimates, strict=True):
            self.assertEqual(scene["id"], estimate["scene_id"])
            self.assertEqual(scene["estimated_seconds"], estimate["estimated_seconds"])
        for index, row in enumerate(result["trace"]):
            self.assertEqual("model", row["actor"])
            self.assertTrue(row["basis"])
            self.assertIn("observation", row)
            expected_next = result["trace"][index + 1]["action"] if index + 1 < len(result["trace"]) else None
            self.assertEqual(expected_next, row["next_action"])

    def test_02_missing_required_information_stops_before_generation(self):
        for field in ("theme", "audience", "platform", "target_seconds", "style"):
            with self.subTest(field=field):
                req = request()
                del req[field]
                result = self.run_mock(req)
                self.assertEqual("needs_information", result["status"])
                self.assert_not_exported(result)
                self.assertFalse(result["revisions"])

    def test_03_invalid_duration_is_rejected_before_model_execution(self):
        for duration in (0, -1, True, "30"):
            with self.subTest(duration=duration):
                with self.assertRaises(ValueError):
                    self.run_mock(request(target_seconds=duration))
        self.assertEqual("needs_information", self.run_mock(request(target_seconds=None))["status"])

    def test_04_no_materials_requests_supplement_without_fabricating(self):
        result = self.run_mock(fixture="no-materials.world.json")
        self.assertEqual("needs_materials", result["status"])
        self.assert_not_exported(result)
        self.assertFalse(result["revisions"])

    def test_05_permanent_tool_failure_is_distinct_from_empty_materials(self):
        result = self.run_mock(fixture="tool-failure.world.json")
        self.assertEqual("tool_failure", result["status"])
        self.assert_not_exported(result)
        self.assertTrue(result["trace"])
        self.assertTrue(result["tool_errors"])

    def test_06_transient_tool_failure_can_be_recovered_by_model(self):
        result = self.run_mock(fixture="transient-failure.world.json")
        self.assert_checked(result, 38)
        calls = [row for row in result["trace"] if row.get("action") == "search_materials"]
        self.assertGreaterEqual(len(calls), 2)
        self.assertTrue(result["tool_errors"], "A recovered tool failure must remain visible.")
        self.assertTrue(any(error.get("resolved") for error in result["tool_errors"]))

    def test_07_over_duration_is_revised_from_38_to_28_and_rechecked(self):
        result = self.run_mock(request(target_seconds=30))
        self.assert_checked(result, 28)
        self.assertEqual(2, len(result["revisions"]))
        first, last = result["revisions"]
        self.assertEqual(38, first["checks"]["estimate_duration"]["total_seconds"])
        self.assertFalse(first["checks"]["estimate_duration"]["within_limit"])
        self.assertEqual(28, last["checks"]["estimate_duration"]["total_seconds"])
        self.assertTrue(last["checks"]["estimate_duration"]["within_limit"])
        self.assertTrue(last["checks"]["check_rules"]["passed"])
        self.assertEqual([14, 14], [scene["duration_seconds"] for scene in last["script"]["scenes"]])

    def test_08_impossible_duration_returns_explicit_unfinished_state(self):
        result = self.run_mock(request(target_seconds=1))
        self.assertEqual("incomplete", result["status"])
        self.assert_not_exported(result)
        self.assertTrue(result["termination"])
        self.assertTrue(result["risks"])

    def test_09_empty_search_causes_a_model_selected_query_rewrite(self):
        result = self.run_mock(request(theme="画面文字能力介绍"))
        self.assert_checked(result, 38)
        searches = [row for row in result["trace"] if row.get("action") == "search_materials"]
        self.assertGreaterEqual(len(searches), 2)
        queries = [row["arguments"]["query"] for row in searches]
        self.assertEqual("画面文字能力介绍", queries[0])
        self.assertIn("字幕", queries[1:])

    def test_10_changed_material_changes_the_generated_factual_claim(self):
        result = self.run_mock(fixture="changed-material.world.json")
        self.assert_checked(result, 38)
        scene = result["script"]["scenes"][0]
        self.assertEqual("支持调整字幕样式。", scene["narration"])
        self.assertEqual("支持调整字幕样式", scene["source_refs"][0]["quote"])

    def test_11_rule_failure_triggers_edit_and_both_checks_on_new_revision(self):
        value = world()
        value["brand"]["max_scenes"] = 1
        result = run(request(), value, MockModel())
        self.assertEqual("completed", result["status"])
        self.assertEqual(2, len(result["revisions"]))
        first, last = result["revisions"]
        self.assertFalse(first["checks"]["check_rules"]["passed"])
        self.assertTrue(last["checks"]["check_rules"]["passed"])
        self.assertTrue(last["checks"]["estimate_duration"]["within_limit"])
        self.assertEqual(1, len(result["script"]["scenes"]))

    def test_12_step_limit_never_exports_an_unchecked_draft(self):
        result = self.run_mock(max_steps=2)
        self.assertEqual("incomplete", result["status"])
        self.assert_not_exported(result)
        self.assertLessEqual(len(result["trace"]), 2)
        self.assertTrue(result["termination"])

    def test_13_completion_cannot_skip_tools(self):
        result = self.sequence([
            action("write_script", {"script": draft()}),
            action("finish", {"kind": "complete"}),
        ])
        self.assert_not_exported(result)

    def test_14_previous_revision_checks_cannot_authorize_a_new_draft(self):
        changed = draft()
        changed["scenes"][0]["duration_seconds"] = 21
        actions = self.checked_actions() + [
            action("write_script", {"script": changed}),
            action("finish", {"kind": "complete"}),
        ]
        result = self.sequence(actions)
        self.assert_not_exported(result)
        self.assertEqual(2, len(result["revisions"]))
        self.assertFalse(result["revisions"][-1]["checks"])

    def test_15_both_checks_are_required_for_each_revision(self):
        for only_check in ("estimate_duration", "check_rules"):
            with self.subTest(only_check=only_check):
                actions = self.checked_actions()[:2] + [
                    action(only_check),
                    action("finish", {"kind": "complete"}),
                ]
                self.assert_not_exported(self.sequence(actions))

    def test_16_checks_can_run_in_reverse_order_for_the_same_revision(self):
        actions = self.checked_actions()[:2] + [
            action("check_rules"),
            action("estimate_duration"),
            action("finish", {"kind": "complete"}),
        ]
        self.assert_checked(self.sequence(actions), 38)

    def test_17_invalid_action_is_recorded_and_cannot_complete(self):
        for invalid in (
            action("unapproved_network_call"),
            {"action": "finish", "arguments": {"kind": "complete"}},
        ):
            with self.subTest(action=invalid):
                self.assert_not_exported(self.sequence([invalid]))

    def test_18_runtime_does_not_mutate_callers_world(self):
        value = world()
        original = copy.deepcopy(value)
        result = run(request(), value, MockModel())
        self.assertEqual("completed", result["status"])
        self.assertEqual(original, value)


class ScriptToolTests(unittest.TestCase):
    def setUp(self):
        self.tools = ScriptTools(world())
        result = self.tools.search("字幕")
        self.retrieved = {material["id"]: material for material in result["materials"]}
        self.assertIn("P01", self.retrieved)

    def assert_rejected(self, script, retrieved=None):
        result = self.tools.check(script, self.retrieved if retrieved is None else retrieved)
        self.assertTrue(result["ok"])
        self.assertFalse(result["passed"])
        self.assertTrue(result["issues"])

    def test_19_exact_retrieved_fact_passes_and_keeps_verifiable_source(self):
        result = self.tools.check(draft(), self.retrieved)
        self.assertTrue(result["passed"])
        self.assertIn(
            {"material_id": "P01", "fact_id": "F1", "quote": "支持字幕"},
            result["verified_sources"],
        )

    def test_20_citing_a_material_not_retrieved_is_rejected(self):
        self.assert_rejected(draft(), retrieved={})

    def test_21_forged_quote_is_rejected_even_when_material_and_fact_exist(self):
        script = draft()
        script["scenes"][0]["source_refs"][0]["quote"] = "支持字幕并提升效率"
        self.assert_rejected(script)

    def test_22_forged_fact_id_is_rejected(self):
        script = draft()
        script["scenes"][0]["source_refs"][0]["fact_id"] = "F999"
        self.assert_rejected(script)

    def test_23_a_real_citation_does_not_support_an_invented_narration(self):
        script = draft()
        script["scenes"][0]["narration"] = "效率提升80%。"
        self.assert_rejected(script)

    def test_24_fabricated_claim_in_subtitles_is_rejected(self):
        script = draft()
        script["scenes"][0]["subtitle"] = "效率提升80%。"
        self.assert_rejected(script)

    def test_25_fabricated_claim_in_title_or_visual_is_rejected(self):
        for field in ("title", "visual"):
            with self.subTest(field=field):
                script = draft()
                if field == "title":
                    script["title"] = "效率提升80%"
                else:
                    script["scenes"][0]["visual"] = "展示效率提升80%的对比图"
                self.assert_rejected(script)

    def test_26_fact_reference_must_belong_to_the_scene_using_it(self):
        script = draft()
        script["scenes"][0]["source_refs"] = []
        script["scenes"][1]["source_refs"] = draft()["scenes"][0]["source_refs"]
        self.assert_rejected(script)

    def test_27_duplicate_scene_ids_are_rejected_as_invalid_structure(self):
        script = draft()
        script["scenes"][1]["id"] = "S1"
        with self.assertRaises(ValueError):
            self.tools.validate_script(script)

    def test_28_long_narration_cannot_hide_behind_a_low_claimed_duration(self):
        script = draft()
        script["scenes"] = script["scenes"][:1]
        script["scenes"][0]["duration_seconds"] = 1
        script["scenes"][0]["narration"] = "支持字幕" * 50
        result = self.tools.estimate(script, 30)
        self.assertTrue(result["ok"])
        self.assertFalse(result["within_limit"])
        self.assertGreaterEqual(result["total_seconds"], 40)

    def test_29_estimate_obeys_each_scene_minimum_and_sums_the_scenes(self):
        script = draft()
        for scene in script["scenes"]:
            scene["duration_seconds"] = 1
            scene["narration"] = "好"
            scene["subtitle"] = "好"
        result = self.tools.estimate(script, 3)
        self.assertEqual(4, result["total_seconds"])
        self.assertEqual(1, result["over_seconds"])
        self.assertFalse(result["within_limit"])
        self.assertEqual(4, sum(scene["estimated_seconds"] for scene in result["scene_estimates"]))

    def test_30_supported_fact_cannot_be_extended_with_unverified_extra_claims(self):
        script = draft()
        script["scenes"][0]["narration"] = "支持字幕，而且全行业效果最佳。"
        self.assert_rejected(script)

    def test_31_neutral_only_script_needs_product_evidence_and_cannot_complete(self):
        script = draft()
        for scene in script["scenes"]:
            scene["narration"] = "从一个想法开始。"
            scene["subtitle"] = "把想法写成一条视频。"
            scene["source_refs"] = []
        checked = self.tools.check(script, self.retrieved)
        self.assertFalse(checked["passed"])
        self.assertIn("no_product_evidence", [issue["code"] for issue in checked["issues"]])
        self.assertFalse(checked["verified_sources"])
        result = run(request(), world(), ScriptModel([
            action("search_materials", {"query": "字幕"}),
            action("write_script", {"script": script}),
            action("estimate_duration"),
            action("check_rules"),
            action("finish", {"kind": "complete"}),
        ]))
        self.assertNotEqual("completed", result["status"])
        self.assertIsNone(result["script"])
        self.assertFalse(result["scenes"])
        self.assertFalse(result["source_ids"])
        self.assertFalse(result["checks"]["check_rules"]["passed"])

    def test_32_long_subtitle_sets_duration_floor_independently_of_short_narration(self):
        script = draft()
        script["scenes"] = script["scenes"][:1]
        script["scenes"][0]["duration_seconds"] = 1
        script["scenes"][0]["subtitle"] = "支持字幕" * 50
        result = self.tools.estimate(script, 30)
        scene = result["scene_estimates"][0]
        self.assertEqual(1, scene["requested_seconds"])
        self.assertLess(scene["speech_seconds"], scene["subtitle_seconds"])
        self.assertEqual(40, scene["subtitle_seconds"])
        self.assertEqual(scene["subtitle_seconds"], scene["estimated_seconds"])
        self.assertEqual(scene["estimated_seconds"], result["total_seconds"])
        self.assertFalse(result["within_limit"])


if __name__ == "__main__":
    unittest.main()
