"""Audit genuine model generation/checking records; no model calls."""
import copy
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT))
from src.tools import ScriptTools


def main():
    world = json.loads((ROOT / "data/world.json").read_text(encoding="utf-8"))
    tools = ScriptTools(world)
    rows = []
    for case in ["normal", "over-duration", "query-rewrite"]:
        output = json.loads((ROOT / f"examples/live-{case}.output.json").read_text(encoding="utf-8"))
        request = json.loads((ROOT / f"examples/live-{case}.input.json").read_text(encoding="utf-8"))
        assert output["mode"] == "live" and output["status"] == "completed"
        retrieved = {}
        script = None
        revision = 0
        checks = {}
        searches = []
        for entry in output["trace"]:
            action, observed = entry["action"], entry["observation"]
            if action == "search_materials" and observed.get("ok"):
                assert observed == tools.search(entry["arguments"]["query"])
                searches.append(entry)
                retrieved.update({item["id"]: item for item in observed["materials"]})
            elif action == "write_script" and observed.get("ok"):
                revision += 1
                script = copy.deepcopy(entry["arguments"]["script"])
                tools.validate_script(script)
                assert script == output["revisions"][revision - 1]["script"] == observed["script"]
                checks = {}
            elif action in {"estimate_duration", "check_rules"} and observed.get("ok"):
                expected = (tools.estimate(script, request["target_seconds"]) if action == "estimate_duration"
                            else tools.check(script, retrieved))
                assert observed == {**expected, "revision": revision}
                checks[action] = observed
        assert checks == output["checks"]
        assert checks["estimate_duration"]["within_limit"] and checks["check_rules"]["passed"]
        assert checks["check_rules"]["verified_sources"]
        assert sum(item["estimated_seconds"] for item in checks["estimate_duration"]["scene_estimates"]) == output["estimated_total_seconds"]
        assert output["estimated_total_seconds"] <= request["target_seconds"]
        assert output["script"]["revision"] == revision
        durations = [record["checks"]["estimate_duration"]["total_seconds"] for record in output["revisions"]
                     if "estimate_duration" in record["checks"]]
        if case == "over-duration":
            assert durations[0] == 38 and revision >= 2 and durations[-1] <= 30
            assert not output["revisions"][0]["checks"]["estimate_duration"]["within_limit"]
        first_empty = bool(searches and not searches[0]["observation"]["materials"])
        if case == "query-rewrite":
            assert first_empty and len({entry["arguments"]["query"] for entry in searches}) >= 2
        rows.append({"scenario": case, "model": output["model"], "status": output["status"],
                     "steps": len(output["trace"]), "revisions": revision, "duration_history": durations,
                     "final_seconds": output["estimated_total_seconds"], "target_seconds": request["target_seconds"],
                     "source_ids": output["source_ids"], "checks_recomputed": True, "latest_revision_checks_passed": True,
                     "first_search_empty": first_empty, "queries": [entry["arguments"]["query"] for entry in searches]})
    report = {"checked_at": datetime.now(timezone(timedelta(hours=8))).isoformat(), "all_passed": True,
              "checks": rows, "archived_failed_attempts": 1,
              "scope": "Three successful real-model runs plus one separately archived format failure; no statistical reliability or actual-video-duration claim."}
    (ROOT / "examples/live-validation-summary.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"live_paths": len(rows), "source_and_timing_checks": "passed"}))


if __name__ == "__main__":
    main()
