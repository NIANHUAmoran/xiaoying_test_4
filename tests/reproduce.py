"""Rebuild actual offline generation/checking records and run the tests; no API calls."""
import json
import os
import subprocess
import sys
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.dont_write_bytecode = True
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"


def write(relative, value):
    (ROOT / relative).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def extract_traces():
    for path in sorted((ROOT / "examples").glob("*.output.json")):
        result = json.loads(path.read_text(encoding="utf-8"))
        write("examples/" + path.name.replace(".output.json", ".trace.json"), {"source_output": path.name,
              **{key: result.get(key) for key in ["request_id", "mode", "model", "generated_at", "trace"]}})


def main():
    started = time.monotonic()
    base = {"theme": "字幕介绍", "audience": "新手创作者", "platform": "短视频", "target_seconds": 45, "style": "简洁"}
    cases = [
        ("normal", {}, [], "world", "completed", 20),
        ("missing-info", {}, ["audience", "target_seconds"], "world", "needs_information", 20),
        ("no-materials", {}, [], "no-materials.world", "needs_materials", 20),
        ("tool-failure", {}, [], "tool-failure.world", "tool_failure", 20),
        ("over-duration", {"target_seconds": 30}, [], "world", "completed", 20),
        ("too-short", {"target_seconds": 1}, [], "world", "incomplete", 20),
        ("rule-limit", {}, [], "rule-limit.world", "completed", 20),
        ("query-rewrite", {"theme": "画面文字能力介绍"}, [], "world", "completed", 20),
        ("transient-failure", {}, [], "transient-failure.world", "completed", 20),
        ("changed-material", {}, [], "changed-material.world", "completed", 20),
        ("step-limit", {}, [], "world", "incomplete", 2),
    ]
    rows = []
    for name, changes, missing, data, expected, limit in cases:
        request = {"request_id": "test4-" + name, **base, **changes}
        for key in missing:
            request.pop(key)
        write(f"examples/{name}.input.json", request)
        process = subprocess.run([sys.executable, "-B", "-m", "src", "--mock", "--input", f"examples/{name}.input.json",
                                  "--data", f"data/{data}.json", "--output", f"examples/{name}.output.json",
                                  "--max-steps", str(limit)], cwd=ROOT, capture_output=True)
        expected_code = 1 if expected in {"tool_failure", "incomplete"} else 0
        if process.returncode != expected_code:
            raise RuntimeError(f"{name}: unexpected exit {process.returncode}")
        output = json.loads((ROOT / f"examples/{name}.output.json").read_text(encoding="utf-8"))
        assert output["status"] == expected, (name, output["status"])
        if name == "over-duration":
            assert output["revisions"][0]["checks"]["estimate_duration"]["total_seconds"] == 38
            assert output["estimated_total_seconds"] == 28
        rows.append({"scenario": name, "status": output["status"], "mode": output["mode"], "exit_code": process.returncode,
                     "revisions": len(output["revisions"]), "estimated_total_seconds": output["estimated_total_seconds"],
                     "data": f"data/{data}.json"})
    for name in ["normal", "over-duration", "query-rewrite"]:
        request = json.loads((ROOT / f"examples/{name}.input.json").read_text(encoding="utf-8"))
        request["request_id"] = "test4-live-" + name
        write(f"examples/live-{name}.input.json", request)
    extract_traces()
    write("examples/run-summary.json", rows)
    suite = unittest.defaultTestLoader.discover(str(ROOT / "tests"))
    with (ROOT / "examples/test-results.txt").open("w", encoding="utf-8") as stream:
        result = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
    write("examples/offline-validation.json", {"checked_at": datetime.now(timezone(timedelta(hours=8))).isoformat(),
          "tests_run": result.testsRun, "failures": len(result.failures), "errors": len(result.errors), "scenarios": len(rows),
          "elapsed_seconds": round(time.monotonic() - started, 2), "live_calls_performed": False, "all_passed": result.wasSuccessful()})
    print(json.dumps({"offline_scenarios": len(rows), "tests": result.testsRun, "passed": result.wasSuccessful()}))
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
