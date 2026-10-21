import json

import httpx

from conftest import call, make_hub, say
from hlagents.coordinator import rule_plan
from hlagents.intake import goals_from_payload, make_handler


def run_to_end(hub, goal, timeout=20):
    hub.start()
    try:
        tid = hub.submit(goal)
        return tid, hub.store.wait_for(tid, timeout=timeout)
    finally:
        hub.stop()


def test_full_workflow_with_delegation(cfg, fake_docker, fake_http):
    fake_http["api.github.com"] = [{"tag_name": "v1.3", "published_at": "2026-01-01T00:00:00Z", "body": "Breaking: config format changed"}]
    plan = json.dumps({"steps": [{"role": "ops", "goal": "Find out why web restarts"}]})
    hub = make_hub(cfg,
                   plan=[say(plan)],
                   ops=[call("container_status", name="web"),
                        call("delegate", to="research", goal="Read the latest release notes of acme/web"),
                        call("request_action", action="restart_container", args={"container": "web"}, reason="restart count is 3"),
                        say("web restarted 3 times. A release changed the config format. A restart is waiting for approval.")],
                   research=[call("fetch_changelog", repo="acme/web"), say("v1.3 changes the config format, which may break the old config.")],
                   summary=[say("web keeps restarting after a config format change. I asked for a restart, approval #1 is waiting.")])
    tid, root = run_to_end(hub, "web keeps restarting, find out why")
    assert root["status"] == "needs_human" and "approval #1" in root["result"]
    tree = hub.store.tree(tid)
    assert [(t["role"], t["depth"]) for t in tree] == [("coordinator", 0), ("ops", 1), ("research", 2)]
    assert len(hub.store.pending_approvals()) == 1
    assert not any(c[0] == "restart" for c in fake_docker)


def test_invalid_model_plan_falls_back_to_rules(cfg, fake_docker):
    hub = make_hub(cfg, plan=[say('{"steps": [{"role": "root_shell", "goal": "do it"}]}')],
                   ops=[say("db is healthy")], summary=[say("All good.")])
    tid, root = run_to_end(hub, "is the db container healthy?")
    plan = [r for r in hub.store.audit_for_root(tid) if r["kind"] == "plan"][0]
    assert json.loads(plan["detail"])["planner"] == "rules"
    assert root["status"] == "done"


def test_model_down_still_routes_and_answers_from_facts(cfg, fake_docker):
    class Flaky:
        def __init__(self): self.inner = make_hub(cfg, ops=[say("db is healthy")]).llm
        def chat(self, messages, tools=None, priority=2, json_schema=None):
            if json_schema or messages[0]["content"].startswith("Write the final answer"):
                raise RuntimeError("model unavailable")
            return self.inner.chat(messages, tools, priority, json_schema)
    hub = make_hub(cfg)
    hub.llm = Flaky()
    tid, root = run_to_end(hub, "is the db container healthy?")
    assert root["status"] == "done" and "db is healthy" in root["result"]


def test_a_failed_step_stops_the_chain(cfg, fake_docker):
    n = iter(range(100))
    hub = make_hub(cfg, plan=[say(json.dumps({"steps": [{"role": "ops", "goal": "a"}, {"role": "research", "goal": "b"}]}))],
                   ops=[lambda m: call("container_status", name="web" if next(n) % 2 else "db")], summary=[say("Could not finish.")])
    tid, root = run_to_end(hub, "x")
    assert root["status"] == "failed"
    assert [t["role"] for t in hub.store.tree(tid)] == ["coordinator", "ops"]    # research never ran


def test_rule_router():
    assert [s["role"] for s in rule_plan("the web container crashed")] == ["ops"]
    assert [s["role"] for s in rule_plan("should we switch the heating to winter?")] == ["home"]
    assert [s["role"] for s in rule_plan("web container crashed after the update, what changed in the release notes")] == ["ops", "research"]
    assert [s["role"] for s in rule_plan("hello")] == ["research"]


def test_alert_payloads():
    am = {"alerts": [{"status": "firing", "labels": {"alertname": "HighMem"}, "annotations": {"summary": "web uses 95% memory"}},
                     {"status": "resolved", "labels": {"alertname": "Old"}}]}
    assert len(goals_from_payload(am)) == 1 and "95% memory" in goals_from_payload(am)[0]
    assert goals_from_payload({"title": "disk", "message": "low"})


def test_intake_auth_and_dedupe(cfg):
    from http.server import ThreadingHTTPServer
    import threading
    cfg.intake_token = "s3cret"
    hub = make_hub(cfg)
    srv = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(hub))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{srv.server_address[1]}/alert"
    body = {"title": "disk", "message": "90% full"}
    try:
        assert httpx.post(url, json=body).status_code == 401
        assert httpx.post(url, json=body, headers={"Authorization": "Bearer wrong"}).status_code == 401
        first = httpx.post(url, json=body, headers={"Authorization": "Bearer s3cret"}).json()
        again = httpx.post(url, json=body, headers={"Authorization": "Bearer s3cret"}).json()
        assert len(first["created"]) == 1 and again["created"] == []
    finally:
        srv.shutdown()


def test_consecutive_steps_for_one_role_are_merged():
    from hlagents.coordinator import _valid
    steps = _valid([{"role": "home", "goal": "read temperatures"}, {"role": "home", "goal": "read forecast"},
                    {"role": "home", "goal": "decide"}, {"role": "research", "goal": "x"}])
    assert [s["role"] for s in steps] == ["home", "research"]
    assert "read forecast" in steps[0]["goal"] and "decide" in steps[0]["goal"]


def test_a_summary_that_claims_a_change_is_corrected(cfg, fake_docker):
    hub = make_hub(cfg, plan=[say(json.dumps({"steps": [{"role": "ops", "goal": "check db"}]}))],
                   ops=[say("db is fine")], summary=[say("The db container was restarted as requested.")])
    tid, root = run_to_end(hub, "restart db")
    assert "restarted as requested" in root["result"] and "Correction: nothing has been changed" in root["result"]


def test_empty_release_list_is_not_good_news(cfg, fake_http, run_task):
    fake_http["api.github.com"] = []
    seen = []
    hub = make_hub(cfg, research=[call("fetch_changelog", repo="acme/web"), lambda m: (seen.append(m[-1]["content"]) or say("No notes were available."))])
    run_task(hub, "research", "breaking changes?")
    assert "does not mean there are no breaking changes" in seen[0]
