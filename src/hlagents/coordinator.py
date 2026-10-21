"""The coordinator turns a request into steps for the specialists and writes the final answer.

It has no tools of its own, so it cannot change anything. A model proposes the plan; if the model fails
or proposes something invalid, plain keyword rules route the request instead.
"""
from __future__ import annotations

import json
import re

from .agents import ROLES
from .guard import clip, fix_claims
from .store import DONE, FAILED, NEEDS_HUMAN

MAX_STEPS = 4
PLAN_SCHEMA = {"type": "object", "required": ["steps"], "properties": {"steps": {
    "type": "array", "maxItems": MAX_STEPS,
    "items": {"type": "object", "required": ["role", "goal"],
              "properties": {"role": {"type": "string", "enum": ROLES}, "goal": {"type": "string"}}}}}}

PLAN_PROMPT = (
    "You are the coordinator of a small team of agents for a home lab.\n"
    "ops: containers, services, logs, restarts.\nhome: heating, hot water, temperatures, solar, weather forecast.\n"
    "research: release notes and reading logs in depth (read only).\n"
    "Split the request into at most 4 steps, in order, each for one role, each with a clear goal. "
    "Use as few steps as possible and never two steps in a row for the same role, because one agent can do several things in one task. Reply with JSON only.")

RULES = [
    ("ops", re.compile(r"container|docker|restart|crash|logs?\b|service|update failed|unhealthy|down\b", re.I)),
    ("home", re.compile(r"heat|winter|summer|hot water|temperature|solar|energy|forecast|cold|warm", re.I)),
    ("research", re.compile(r"changelog|release notes?|what changed|breaking|upgrade", re.I)),
]


def rule_plan(goal: str) -> list[dict]:
    roles = [r for r, rx in RULES if rx.search(goal)] or ["research"]
    return [{"role": r, "goal": goal} for r in roles[:MAX_STEPS]]


def _valid(steps) -> list[dict] | None:
    if not isinstance(steps, list) or not 1 <= len(steps) <= MAX_STEPS:
        return None
    out = []
    for s in steps:
        if not isinstance(s, dict) or s.get("role") not in ROLES or not str(s.get("goal", "")).strip():
            return None
        goal = str(s["goal"]).strip()[:600]
        if out and out[-1]["role"] == s["role"]:       # one agent can do consecutive steps in a single task
            out[-1]["goal"] = (out[-1]["goal"] + " Then: " + goal)[:900]
        else:
            out.append({"role": s["role"], "goal": goal})
    return out


def plan(hub, goal: str, priority: int, task_id: int) -> list[dict]:
    try:
        msg = hub.llm.chat([{"role": "system", "content": PLAN_PROMPT}, {"role": "user", "content": goal}],
                           priority=priority, json_schema=PLAN_SCHEMA)
        steps = _valid(json.loads(msg["content"]).get("steps"))
        if steps:
            hub.store.audit(task_id, "coordinator", "plan", {"planner": "model", "steps": steps})
            return steps
        reason = "model plan was invalid"
    except Exception as e:  # noqa: BLE001
        reason = f"model plan failed: {type(e).__name__}"
    steps = rule_plan(goal)
    hub.store.audit(task_id, "coordinator", "plan", {"planner": "rules", "why": reason, "steps": steps})
    return steps


def run_root(hub, task: dict) -> tuple[str, str]:
    store, cfg = hub.store, hub.cfg
    steps = plan(hub, task["goal"], task["priority"], task["id"])
    results, worst = [], DONE
    for i, step in enumerate(steps, 1):
        context = "\n\n".join(f"Step {n} ({r['role']}): {clip(r['result'], 1200)}" for n, r in enumerate(results, 1))
        tid = store.create_task(step["role"], step["goal"], requester="coordinator", parent_id=task["id"],
                                priority=task["priority"], context=context, max_depth=cfg.max_depth)
        child = store.wait_for(tid, timeout=cfg.time_budget_s * 2)
        results.append({"role": step["role"], "goal": step["goal"], "status": child["status"], "result": child["result"]})
        if child["status"] == NEEDS_HUMAN and worst == DONE:
            worst = NEEDS_HUMAN
        if child["status"] not in (DONE, NEEDS_HUMAN):
            worst = FAILED
            break
    pending = [a for a in store.pending_approvals() if store.get_task(a["task_id"])["root_id"] == task["id"]]
    if pending and worst == DONE:
        worst = NEEDS_HUMAN
    return worst, _summarise(hub, task, results, pending)


def _summarise(hub, task: dict, results: list[dict], pending: list[dict]) -> str:
    facts = "\n\n".join(f"[{r['role']}] {r['goal']}\nStatus: {r['status']}\n{clip(r['result'], 1500)}" for r in results)
    waiting = "\n".join(f"- approval #{a['id']}: {a['action']} {json.dumps(a['args'])}" for a in pending)
    prompt = ("Write the final answer for the household in a few sentences, from the results below. Say what was found and "
              "what you recommend. If approvals are waiting, say so and give their numbers. Nothing has been changed yet, so never say "
              "that something was set, switched or restarted. Do not turn missing information into good news: if notes or data were "
              "not found, say they were not found.")
    try:
        msg = hub.llm.chat([{"role": "system", "content": prompt},
                            {"role": "user", "content": f"Request: {task['goal']}\n\n{facts}\n\nWaiting for approval:\n{waiting or 'none'}"}],
                           priority=task["priority"])
        text = fix_claims((msg.get("content") or "").strip())
        if text:
            return text + (f"\n\nWaiting for approval: {', '.join('#' + str(a['id']) for a in pending)}" if pending and "#" not in text else "")
    except Exception:  # noqa: BLE001
        pass
    return facts + (f"\n\nWaiting for approval:\n{waiting}" if waiting else "")
