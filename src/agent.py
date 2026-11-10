import copy
import hashlib
import json
from datetime import datetime, timezone

from .models import ModelServiceError
from .tools import ScriptTools


FIELDS = ["theme", "audience", "platform", "target_seconds", "style"]
SCHEMAS = {"search_materials": {"query"}, "write_script": {"script"},
           "estimate_duration": set(), "check_rules": set(), "finish": {"kind"}}


def validate_request(request):
    if not isinstance(request, dict):
        raise ValueError("输入必须为 JSON 对象")
    missing = [key for key in FIELDS if request.get(key) is None or request.get(key) == ""]
    for key in FIELDS:
        if key in missing:
            continue
        if key == "target_seconds":
            if type(request[key]) is not int or not 1 <= request[key] <= 600:
                raise ValueError("target_seconds 必须为 1..600 的整数")
        elif not isinstance(request[key], str) or not request[key].strip():
            raise ValueError("主题、受众、平台和风格必须为非空字符串")
    return missing


def validate_decision(value):
    if not isinstance(value, dict) or set(value) != {"action", "arguments", "basis"}:
        raise ValueError("invalid_decision_fields")
    action, args = value["action"], value["arguments"]
    if action not in SCHEMAS or not isinstance(args, dict) or set(args) != SCHEMAS[action]:
        raise ValueError("invalid_action_or_arguments")
    if not isinstance(value["basis"], str) or not 1 <= len(value["basis"]) <= 500:
        raise ValueError("invalid_basis")
    if action == "search_materials" and (not isinstance(args["query"], str) or not args["query"].strip()):
        raise ValueError("invalid_query")
    if action == "write_script" and not isinstance(args["script"], dict):
        raise ValueError("invalid_script")
    if action == "finish" and args["kind"] not in {"complete", "need_materials", "tool_failure", "cannot_meet", "stop"}:
        raise ValueError("invalid_finish_kind")


def finish(kind, state):
    revision = len(state["revisions"])
    checks = state["checks"]
    if kind == "complete":
        if not state["draft"]:
            return {"ok": False, "error": "script_required"}
        if any(name not in checks or checks[name]["revision"] != revision for name in ["estimate_duration", "check_rules"]):
            return {"ok": False, "error": "fresh_checks_required", "revision": revision}
        if not checks["estimate_duration"].get("within_limit") or not checks["check_rules"].get("passed"):
            return {"ok": False, "error": "checks_not_passed", "revision": revision}
        if not checks["check_rules"].get("verified_sources"):
            return {"ok": False, "error": "product_evidence_required"}
        return {"ok": True, "status": "completed", "reason": None}
    active_errors = [error for error in state["errors"] if not error.get("resolved") and not error.get("superseded")]
    if kind == "need_materials":
        if state["materials"] or not any(search.get("ok") for search in state["searches"]) or active_errors:
            return {"ok": False, "error": "material_absence_not_verified"}
        return {"ok": True, "status": "needs_materials", "reason": "no_supporting_materials"}
    if kind == "tool_failure":
        if not active_errors:
            return {"ok": False, "error": "no_unresolved_tool_error"}
        return {"ok": True, "status": "tool_failure", "reason": "tool_failure"}
    if kind == "cannot_meet":
        if not any(not result.get("within_limit", result.get("passed", True)) for result in checks.values()):
            return {"ok": False, "error": "failed_check_required"}
        reason = "duration_limit_unmet" if not checks.get("estimate_duration", {}).get("within_limit", True) else "rules_not_met"
        return {"ok": True, "status": "incomplete", "reason": reason}
    return {"ok": True, "status": "incomplete", "reason": "model_stopped"}


def run(request, world, model, max_steps=20):
    missing = validate_request(request)
    if type(max_steps) is not int or not 1 <= max_steps <= 100:
        raise ValueError("max_steps 必须为 1..100 的整数")
    identity = request.get("request_id") or "video-" + hashlib.sha256(json.dumps(request, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]
    if missing:
        return {"request_id": identity, "status": "needs_information", "reason": "missing_required_input", "missing_fields": missing,
                "mode": "validation", "model": None, "model_calls": 0, "script": None, "last_draft": None,
                "title": None, "scenes": [], "estimated_total_seconds": None, "source_ids": [], "risks": [],
                "revisions": [], "checks": {}, "gaps": ["请补充：" + ", ".join(missing)], "termination": "input_incomplete",
                "generated_at": datetime.now(timezone.utc).isoformat(), "trace": [{"step": 1, "actor": "runtime", "action": "validate_input",
                "arguments": {}, "basis": "关键输入缺失", "observation": {"missing_fields": missing}, "next_action": None}]}
    tools = ScriptTools(world)
    state = {"searches": [], "materials": {}, "draft": None, "revisions": [], "checks": {},
             "errors": [], "attempts": {}, "last_observation": None}
    known_theme = any(word in request["theme"] for word in ["字幕", "画面文字", "文字能力", "视频文字"])
    canonical_query = "字幕" if known_theme else None
    trace, terminal = [], None
    termination = "step_limit"
    for step in range(1, max_steps + 1):
        context = {"request": request, "brand": world["brand"], "timing": world["timing"], "canonical_query": canonical_query,
                   "state": state, "remaining_steps": max_steps - step + 1}
        decision = None
        try:
            decision = model.decide(copy.deepcopy(context))
            validate_decision(decision)
        except Exception as exc:
            error = {"step": step, "actor": "model", "error": "model_error", "detail": type(exc).__name__}
            if isinstance(exc, ModelServiceError):
                error["service_error"] = str(exc)
            if isinstance(decision, dict):
                error["response_fields"] = list(decision)
                error["returned_action"] = str(decision.get("action", ""))[:64]
            trace.append(error)
            termination = "model_error"
            break
        action, args = decision["action"], decision["arguments"]
        entry = {"step": step, "actor": "model", "model_output_format": getattr(model, "last_output_format", "structured"), **decision}
        if action == "finish":
            result = finish(args["kind"], state)
        elif action == "write_script":
            try:
                tools.validate_script(args["script"])
                state["draft"] = copy.deepcopy(args["script"])
                state["checks"] = {}
                number = len(state["revisions"]) + 1
                state["revisions"].append({"revision": number, "script": copy.deepcopy(state["draft"]), "checks": {}})
                for error in state["errors"]:
                    if error["action"] in {"estimate_duration", "check_rules"}:
                        error["superseded"] = True
                result = {"ok": True, "revision": number, "script": copy.deepcopy(state["draft"]), "checks_invalidated": True}
            except ValueError:
                result = {"ok": False, "error": "invalid_script_shape"}
        else:
            revision = len(state["revisions"])
            state["attempts"][action] = state["attempts"].get(action, 0) + 1
            rule = next((item for item in world.get("failures", []) if item["tool"] == action), None)
            if action != "search_materials" and state["draft"] is None:
                result = {"ok": False, "error": "script_required"}
            elif rule and (rule["mode"] == "always" or state["attempts"][action] == 1):
                result = {"ok": False, "error": "injected_tool_failure", "retryable": rule["mode"] == "once"}
            elif action == "search_materials":
                result = tools.search(args["query"])
                if result["ok"]:
                    for material in result["materials"]:
                        state["materials"][material["id"]] = copy.deepcopy(material)
            elif action == "estimate_duration":
                result = {**tools.estimate(state["draft"], request["target_seconds"]), "revision": revision}
            else:
                result = {**tools.check(state["draft"], state["materials"]), "revision": revision}
            if action == "search_materials":
                state["searches"].append({"query": args["query"], **copy.deepcopy(result)})
            elif result.get("ok"):
                state["checks"][action] = copy.deepcopy(result)
                state["revisions"][-1]["checks"][action] = copy.deepcopy(result)
            if result.get("ok"):
                for error in state["errors"]:
                    if error["action"] == action and error["arguments"] == args and error.get("revision") == revision:
                        error["resolved"] = True
            else:
                state["errors"].append({"action": action, "arguments": args, "revision": revision, **copy.deepcopy(result)})
        entry["observation"] = copy.deepcopy(result)
        trace.append(entry)
        state["last_observation"] = {"action": action, "arguments": args, **copy.deepcopy(result)}
        if action == "finish" and result["ok"]:
            terminal = result
            termination = "finished"
            break
    for index, entry in enumerate(trace):
        entry["next_action"] = trace[index + 1].get("action", "model_error") if index + 1 < len(trace) else None
    terminal = terminal or {"status": "incomplete", "reason": termination}
    complete = terminal["status"] == "completed"
    duration = state["checks"].get("estimate_duration", {})
    rules = state["checks"].get("check_rules", {})
    risks = copy.deepcopy(rules.get("issues", []))
    if duration and not duration["within_limit"]:
        risks.append({"code": "duration_exceeded", "detail": str(duration["over_seconds"]) + " seconds over target"})
    exported = None
    if complete:
        exported = copy.deepcopy(state["draft"])
        estimates = {item["scene_id"]: item["estimated_seconds"] for item in duration["scene_estimates"]}
        for scene in exported["scenes"]:
            scene["estimated_seconds"] = estimates[scene["id"]]
        exported.update(revision=len(state["revisions"]), estimated_total_seconds=duration["total_seconds"])
    gaps = [] if complete else [terminal["reason"]]
    if terminal["status"] == "needs_materials":
        gaps.append("请提供支持主题的产品素材或补充可检索关键词")
    return {"request_id": identity, "status": terminal["status"], "reason": terminal["reason"], "missing_fields": [],
            "mode": model.mode, "model": model.name, "generated_at": datetime.now(timezone.utc).isoformat(),
            "max_steps": max_steps, "model_calls": len(trace), "termination": termination,
            "script": exported, "last_draft": state["draft"], "title": exported["title"] if complete else None,
            "scenes": exported["scenes"] if complete else [], "estimated_total_seconds": duration.get("total_seconds"),
            "source_ids": sorted({ref["material_id"] for ref in rules.get("verified_sources", [])}) if complete else [],
            "risks": risks, "gaps": gaps, "checks": state["checks"], "revisions": state["revisions"],
            "tool_errors": state["errors"], "retrieved_source_ids": sorted(state["materials"]), "trace": trace}
