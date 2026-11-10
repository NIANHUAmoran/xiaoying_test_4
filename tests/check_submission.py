"""Verify the local submission and its paired, source-grounded execution records.

This script makes no network requests. Replaying deterministic business checks
tests the recorded evidence, not whether a remote model actually made a choice.
"""

from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import re
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT))
from src.tools import ScriptTools  # noqa: E402


ENTRIES = {
    "README.md", "requirements.txt", ".env.example", ".gitignore",
    "src", "tests", "examples", "data", "docs",
}
DOCS = {
    "01-requirements.md", "02-solution.md", "03-evaluation.md",
    "04-ai-usage.md", "05-retrospective.md",
}
# A user's gitignored local .env is allowed for running the CLI. Packaging and
# secret scans must still exclude it from any delivered repository/archive.
LOCAL_ONLY = {".env", ".git", ".venv", ".runtime", "__pycache__"}
CASE_DATA = {
    "normal": "world.json",
    "missing-info": "world.json",
    "no-materials": "no-materials.world.json",
    "tool-failure": "tool-failure.world.json",
    "over-duration": "world.json",
    "too-short": "world.json",
    "rule-limit": "rule-limit.world.json",
    "query-rewrite": "world.json",
    "transient-failure": "transient-failure.world.json",
    "changed-material": "changed-material.world.json",
    "step-limit": "world.json",
    "live-normal": "world.json",
    "live-over-duration": "world.json",
    "live-query-rewrite": "world.json",
    "live-format-failure": "world.json",
}
EXPECTED_STATUS = {
    "normal": "completed", "missing-info": "needs_information",
    "no-materials": "needs_materials", "tool-failure": "tool_failure",
    "over-duration": "completed", "too-short": "incomplete",
    "rule-limit": "completed", "query-rewrite": "completed",
    "transient-failure": "completed", "changed-material": "completed",
    "step-limit": "incomplete", "live-normal": "completed",
    "live-over-duration": "completed", "live-query-rewrite": "completed",
    "live-format-failure": "incomplete",
}
CHECK_ACTIONS = {"estimate_duration", "check_rules"}
ALL_ACTIONS = CHECK_ACTIONS | {"search_materials", "write_script", "finish"}


def read(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def require(condition, message):
    if not condition:
        raise ValueError(message)


def completed_script(output, request, case):
    """Check exported fields against the final raw draft and fresh checks."""
    script = output["script"]
    require(isinstance(script, dict), f"{case}: completed script is missing")
    revision = output["revisions"][-1]["revision"]
    require(script["revision"] == revision, f"{case}: exported revision is stale")
    raw = copy.deepcopy(script)
    raw.pop("revision")
    raw.pop("estimated_total_seconds")
    for scene in raw["scenes"]:
        scene.pop("estimated_seconds")
    require(raw == output["last_draft"] == output["revisions"][-1]["script"],
            f"{case}: exported script differs from the checked draft")
    checks = output["checks"]
    require(set(checks) == CHECK_ACTIONS, f"{case}: both final checks are required")
    require(all(result.get("revision") == revision and result.get("ok") is True
                for result in checks.values()), f"{case}: checks are not fresh")
    duration, rules = checks["estimate_duration"], checks["check_rules"]
    require(duration["within_limit"] and rules["passed"] and rules["verified_sources"],
            f"{case}: failed or unsupported draft was exported")
    require(output["title"] == script["title"] and output["scenes"] == script["scenes"],
            f"{case}: top-level script fields differ from the checked export")
    estimates = duration["scene_estimates"]
    require([row["scene_id"] for row in estimates] == [row["id"] for row in script["scenes"]],
            f"{case}: scene estimates do not match storyboard scene IDs")
    require(all(scene["estimated_seconds"] == estimate["estimated_seconds"]
                and scene["duration_seconds"] == estimate["requested_seconds"]
                for scene, estimate in zip(script["scenes"], estimates, strict=True)),
            f"{case}: exported scene timings differ from the tool results")
    total = sum(row["estimated_seconds"] for row in estimates)
    require(total == duration["total_seconds"] == script["estimated_total_seconds"]
            == output["estimated_total_seconds"] and total <= request["target_seconds"],
            f"{case}: total time is inconsistent or over target")
    expected_sources = sorted({ref["material_id"] for ref in rules["verified_sources"]})
    require(output["source_ids"] == expected_sources and expected_sources,
            f"{case}: source IDs differ from verified evidence")


def replay_record(request, output, world, case):
    """Recheck recorded tools using the materials observed at that exact step."""
    tools = ScriptTools(world)
    materials, revisions, checks = {}, [], {}
    draft = None
    source_refs_checked = 0
    trace = output["trace"]
    require(isinstance(trace, list) and trace, f"{case}: Trace is missing")
    for index, row in enumerate(trace):
        require(row["step"] == index + 1, f"{case}: nonsequential Trace steps")
        next_action = trace[index + 1].get("action", "model_error") if index + 1 < len(trace) else None
        require(row.get("next_action") == next_action, f"{case}: incorrect next action")
        if case == "missing-info":
            require(row.get("actor") == "runtime" and row.get("action") == "validate_input",
                    f"{case}: missing input must stop before model invocation")
            continue
        if case == "live-format-failure" and row.get("error") == "model_error":
            require(index == len(trace) - 1 and row.get("actor") == "model"
                    and row.get("detail") == "JSONDecodeError"
                    and output["reason"] == output["termination"] == "model_error",
                    f"{case}: archived model format failure is inconsistent")
            continue
        require(row.get("actor") == "model" and row.get("action") in ALL_ACTIONS,
                f"{case}: invalid or unproven decision entry")
        require(isinstance(row.get("basis"), str) and row["basis"].strip(),
                f"{case}: brief decision basis is missing")
        require(isinstance(row.get("arguments"), dict) and isinstance(row.get("observation"), dict),
                f"{case}: tool parameters or returned observation are missing")
        action, arguments, observation = row["action"], row["arguments"], row["observation"]
        if action == "search_materials" and observation.get("ok"):
            require(observation == tools.search(arguments["query"]),
                    f"{case}: successful retrieval differs from the selected world's tool result")
            for material in observation["materials"]:
                materials[material["id"]] = copy.deepcopy(material)
        elif action == "write_script" and observation.get("ok"):
            draft = copy.deepcopy(arguments["script"])
            tools.validate_script(draft)
            require(observation["script"] == draft and observation["revision"] == len(revisions) + 1
                    and observation.get("checks_invalidated") is True,
                    f"{case}: generated script revision is inconsistent")
            revisions.append({"revision": len(revisions) + 1, "script": draft, "checks": {}})
            checks = {}
        elif action in CHECK_ACTIONS and observation.get("ok"):
            require(draft is not None and not arguments,
                    f"{case}: a check must target the current draft without replacement arguments")
            actual = tools.estimate(draft, request["target_seconds"]) if action == "estimate_duration" else tools.check(draft, materials)
            actual["revision"] = len(revisions)
            require(observation == actual,
                    f"{case}: recorded {action} differs from a fresh deterministic check")
            checks[action] = copy.deepcopy(observation)
            revisions[-1]["checks"][action] = copy.deepcopy(observation)
            if action == "check_rules":
                source_refs_checked += len(observation["verified_sources"])
        elif action == "finish" and observation.get("ok"):
            require(index == len(trace) - 1 and observation["status"] == output["status"],
                    f"{case}: accepted finish does not match actual task status")
        elif not observation.get("ok") and action != "finish":
            require(isinstance(observation.get("error"), str) and observation["error"],
                    f"{case}: failed tool observation needs an explicit error")
    require(output["revisions"] == revisions and output["checks"] == checks,
            f"{case}: history or final checks differ from the actual Trace")
    require(output["last_draft"] == draft, f"{case}: last_draft differs from generated history")
    if case != "missing-info":
        require(output["retrieved_source_ids"] == sorted(materials),
                f"{case}: retrieved material IDs differ from successful searches")
        require(output["model_calls"] == len(trace) <= output["max_steps"],
                f"{case}: model call budget is inconsistent")
    else:
        require(output["model_calls"] == 0 and output["missing_fields"] and not revisions,
                f"{case}: missing input did not stop at validation")
    if output["status"] == "completed":
        completed_script(output, request, case)
    else:
        require(output["script"] is None and output["title"] is None
                and output["scenes"] == [] and output["source_ids"] == [],
                f"{case}: unfinished content was exported as a final script")
        require(output["gaps"], f"{case}: unfinished outcome needs an explanation")
    return source_refs_checked


def searches(output):
    return [row for row in output["trace"] if row.get("action") == "search_materials"]


def check_correction(output, case):
    revisions = output["revisions"]
    require(len(revisions) >= 2, f"{case}: no script correction was recorded")
    first, last = revisions[0], revisions[-1]
    require(first["checks"]["estimate_duration"]["total_seconds"] == 38
            and not first["checks"]["estimate_duration"]["within_limit"],
            f"{case}: the 38-second rejected draft is missing")
    require(last["checks"]["estimate_duration"]["within_limit"]
            and last["checks"]["estimate_duration"]["total_seconds"] < 38
            and set(last["checks"]) == CHECK_ACTIONS
            and first["script"] != last["script"],
            f"{case}: a shorter repaired draft with both fresh checks is missing")
    if case == "over-duration":
        require(last["checks"]["estimate_duration"]["total_seconds"] == 28
                and all(set(revision["checks"]) == CHECK_ACTIONS for revision in revisions),
                f"{case}: the deterministic 38-to-28 repair and checks are missing")


def main():
    root_entries = {path.name for path in ROOT.iterdir()} - LOCAL_ONLY
    require(root_entries == ENTRIES, "Unexpected or missing submission root entries")
    require({path.name for path in (ROOT / "docs").iterdir()} == DOCS,
            "The five required documents must be present")
    require((ROOT / "src/__main__.py").is_file(), "Executable CLI entry is missing")
    require(bool(list((ROOT / "tests").glob("test_*.py"))), "Executable tests are missing")
    require(not list((ROOT / "examples").rglob("*.py")), "Verification scripts belong in tests")
    require(not [path for path in ROOT.rglob(".env") if path != ROOT / ".env"],
            "Nested .env files must not be included in the submission")
    outputs = {}
    source_refs_checked = 0
    for case, data_name in CASE_DATA.items():
        request, output, extracted = [read(ROOT / f"examples/{case}.{kind}.json")
                                      for kind in ["input", "output", "trace"]]
        require(request["request_id"] == output["request_id"] == extracted["request_id"],
                f"{case}: inconsistent request IDs")
        require(extracted["source_output"] == case + ".output.json",
                f"{case}: extracted Trace points at the wrong output")
        require(extracted["trace"] == output["trace"],
                f"{case}: extracted Trace differs from actual output")
        require(output["status"] == EXPECTED_STATUS[case], f"{case}: unexpected task status")
        mode = "validation" if case == "missing-info" else "live" if case.startswith("live-") else "mock"
        require(output["mode"] == mode == extracted["mode"],
                f"{case}: real-model/Mock provenance is inconsistent")
        if mode == "live":
            require(isinstance(output.get("model"), str) and output["model"]
                    and "mock" not in output["model"].casefold(),
                    f"{case}: real model identity is missing")
        source_refs_checked += replay_record(request, output, read(ROOT / "data" / data_name), case)
        outputs[case] = output

    for case in ("normal", "live-normal"):
        require(outputs[case]["estimated_total_seconds"] == 38,
                f"{case}: expected normal 38-second actual output is missing")
    for case in ("over-duration", "live-over-duration"):
        check_correction(outputs[case], case)
    for case in ("query-rewrite", "live-query-rewrite"):
        rows = searches(outputs[case])
        require(len(rows) >= 2 and rows[0]["observation"].get("ok")
                and not rows[0]["observation"]["materials"]
                and len({row["arguments"]["query"] for row in rows}) >= 2
                and any(row["observation"].get("materials") for row in rows[1:]),
                f"{case}: no query adjustment after an empty result")
    require(not outputs["no-materials"]["revisions"]
            and all(row["observation"].get("ok") and not row["observation"]["materials"]
                    for row in searches(outputs["no-materials"])),
            "No-materials case must preserve successful but empty retrievals")
    failed = outputs["tool-failure"]
    require(failed["tool_errors"] and any(not row["observation"].get("ok") for row in searches(failed)),
            "Permanent tool failure evidence is missing")
    recovered = outputs["transient-failure"]
    require(any(error.get("resolved") for error in recovered["tool_errors"])
            and any(not row["observation"].get("ok") for row in searches(recovered))
            and any(row["observation"].get("materials") for row in searches(recovered)),
            "Recovered failure must remain visible alongside a successful retry")
    short = outputs["too-short"]
    require(not short["checks"]["estimate_duration"]["within_limit"]
            and short["estimated_total_seconds"] > 1 and short["risks"],
            "Impossible duration must retain the failed estimate and risks")
    limited = outputs["rule-limit"]["revisions"]
    require(len(limited) >= 2 and not limited[0]["checks"]["check_rules"]["passed"]
            and any(issue["code"] == "scene_count_exceeded"
                    for issue in limited[0]["checks"]["check_rules"]["issues"])
            and len(limited[-1]["script"]["scenes"]) == 1
            and set(limited[-1]["checks"]) == CHECK_ACTIONS
            and outputs["rule-limit"]["estimated_total_seconds"] == 20,
            "Rule-driven edit and fresh checks are missing")
    require(outputs["changed-material"]["last_draft"] != outputs["normal"]["last_draft"]
            and "支持调整字幕样式" in json.dumps(outputs["changed-material"]["last_draft"], ensure_ascii=False),
            "Changing the factual source did not change the script")
    require(outputs["step-limit"]["termination"] == "step_limit"
            and len(outputs["step-limit"]["trace"]) == outputs["step-limit"]["max_steps"],
            "Step exhaustion must return an explicit unfinished result")
    archived = outputs["live-format-failure"]
    require(archived["request_id"] == outputs["live-over-duration"]["request_id"]
            and len(archived["trace"]) == 4
            and archived["trace"][-1].get("detail") == "JSONDecodeError"
            and archived["checks"]["estimate_duration"]["total_seconds"] == 38
            and not archived["checks"]["estimate_duration"]["within_limit"]
            and "check_rules" not in archived["checks"]
            and all("model_output_format" not in row for row in archived["trace"]),
            "Original live format failure must remain archived without invented metadata or checks")

    offline = read(ROOT / "examples/offline-validation.json")
    tests_run = offline["tests_run"]
    require(offline.get("all_passed") is True and type(tests_run) is int and tests_run >= 32
            and offline.get("scenarios") == 11,
            "Expected offline verification is incomplete")
    test_report = (ROOT / "examples/test-results.txt").read_text(encoding="utf-8")
    require(re.search(rf"Ran {tests_run} tests\b", test_report)
            and test_report.rstrip().endswith("OK"),
            "Actual passing test report does not match the offline summary")
    live = read(ROOT / "examples/live-validation-summary.json")
    require(live.get("all_passed") is True and len(live.get("checks", [])) == 3,
            "Three real-model validation paths must be recorded")
    pending_report = (ROOT / "examples/submission-check.json").resolve()
    for path in [ROOT / "README.md", *sorted((ROOT / "docs").glob("*.md")), ROOT / "examples/README.md"]:
        for target in re.findall(r"\]\(([^)]+)\)", path.read_text(encoding="utf-8")):
            target = target.strip("<>")
            if target.startswith(("http:", "https:", "#")):
                continue
            resolved = (path.parent / target.split("#")[0]).resolve()
            require(resolved.is_relative_to(ROOT),
                    f"Document link depends on an external workspace file: {path.name}")
            require(resolved.exists() or resolved == pending_report,
                    f"Broken document link: {path.name} -> {target}")
    result = {
        "checked_at": datetime.now(timezone(timedelta(hours=8))).isoformat(),
        "all_passed": True, "root_entries": sorted(root_entries), "documents": sorted(DOCS),
        "evidence_groups": len(CASE_DATA), "offline_runs": 11, "live_paths": 3,
        "archived_live_failures": 1,
        "unit_tests": tests_run, "trace_matches_actual_output": True,
        "verified_source_records_checked": source_refs_checked,
        "citations_match_successfully_retrieved_materials": True,
        "factual_text_rechecked_against_exact_sources": True,
        "latest_revision_has_both_fresh_checks": True,
        "per_scene_and_total_timings_match": True,
        "five_required_scenarios_covered": True,
        "offline_over_duration_repair_38_to_28_observed": True,
        "live_over_duration_repair_observed": True,
        "live_repaired_seconds": outputs["live-over-duration"]["estimated_total_seconds"],
        "original_live_format_failure_preserved": True,
        "rule_failure_followed_by_revision_and_rechecks": True,
        "material_change_changes_script": True, "query_rewrite_observed": True,
        "unfinished_drafts_not_exported_as_final": True, "document_links_valid": True,
        "scope": "Local artifact consistency and deterministic tool replay; no model service was called.",
    }
    pending_report.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"submission": "passed", "evidence_groups": len(CASE_DATA),
                      "tests": tests_run, "verified_source_records_checked": source_refs_checked}))


if __name__ == "__main__":
    main()
