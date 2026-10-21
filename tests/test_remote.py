import asyncio
import threading
from http.server import ThreadingHTTPServer

import httpx
import pytest

from conftest import make_hub
from hlagents import ha_bridge, mcp_server, notify
from hlagents.api import make_handler


@pytest.fixture
def api(cfg):
    cfg.api_token = "tok"
    hub = make_hub(cfg)
    srv = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(hub))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    yield hub, base, {"Authorization": "Bearer tok"}
    srv.shutdown()


def pending_approval(hub, action="restart_container", args=None):
    t = hub.store.create_task("ops", "x", "human")
    aid = hub.store.create_approval(t, action, args or {"container": "web"}, "because")
    return aid


# ---- API -------------------------------------------------------------------------------------

def test_api_requires_a_token(api):
    hub, base, _ = api
    assert httpx.get(base + "/requests").status_code == 401
    assert httpx.get(base + "/requests", headers={"Authorization": "Bearer nope"}).status_code == 401
    assert httpx.post(base + "/requests", json={"goal": "x"}).status_code == 401


def test_api_without_a_configured_token_refuses_everything(cfg):
    cfg.api_token = ""
    hub = make_hub(cfg)
    srv = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(hub))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        assert httpx.get(f"http://127.0.0.1:{srv.server_address[1]}/requests", headers={"Authorization": "Bearer anything"}).status_code == 401
    finally:
        srv.shutdown()


def test_submit_and_read_a_request(api):
    hub, base, h = api
    rid = httpx.post(base + "/requests", json={"goal": "is db healthy?"}, headers=h).json()["id"]
    t = httpx.get(f"{base}/requests/{rid}", headers=h).json()
    assert t["status"] == "open" and t["goal"] == "is db healthy?"
    assert httpx.post(base + "/requests", json={}, headers=h).status_code == 400
    assert httpx.get(base + "/requests/9999", headers=h).status_code == 404
    assert httpx.get(f"{base}/requests/{rid}/audit", headers=h).json()[0]["kind"] == "task_created"


def test_approvals_are_listed_without_their_token(api):
    hub, base, h = api
    pending_approval(hub)
    rows = httpx.get(base + "/approvals", headers=h).json()
    assert len(rows) == 1 and "token" not in rows[0]
    assert hub.store.pending_approvals()[0]["token"]          # the token exists, it just never leaves


def test_approve_and_deny_over_the_api(api):
    hub, base, h = api
    a, b = pending_approval(hub), pending_approval(hub, args={"container": "db"})
    r = httpx.post(f"{base}/approvals/{a}/approve", headers=h)
    assert r.status_code == 200 and "dry run" in r.json()["result"]
    assert httpx.post(f"{base}/approvals/{a}/approve", headers=h).status_code == 409      # not twice
    assert httpx.post(f"{base}/approvals/{b}/deny", headers=h).status_code == 200
    assert hub.store.get_approval(b)["status"] == "denied"


# ---- phone buttons ---------------------------------------------------------------------------

def test_button_with_the_right_token_decides(cfg):
    hub = make_hub(cfg)
    aid = pending_approval(hub)
    token = hub.store.get_approval(aid)["token"]
    msg = ha_bridge.handle_action(hub, f"HLAGENTS_APPROVE_{aid}_{token}")
    assert "Approved" in msg and hub.store.get_approval(aid)["decided_by"] == "phone"


def test_button_with_a_wrong_token_is_ignored_and_logged(cfg):
    hub = make_hub(cfg)
    aid = pending_approval(hub)
    assert ha_bridge.handle_action(hub, f"HLAGENTS_APPROVE_{aid}_forged") is None
    assert hub.store.get_approval(aid)["status"] == "pending"
    assert any(r["kind"] == "approval_bad_token" for r in hub.store._all("select * from audit"))


def test_other_notification_actions_are_not_ours(cfg):
    hub = make_hub(cfg)
    assert ha_bridge.handle_action(hub, "DOORBELL_TEACH") is None
    assert ha_bridge.handle_action(hub, "HLAGENTS_APPROVE_999_abc") is None


def test_deny_button_and_a_second_press(cfg):
    hub = make_hub(cfg)
    aid = pending_approval(hub)
    token = hub.store.get_approval(aid)["token"]
    assert "denied" in ha_bridge.handle_action(hub, f"HLAGENTS_DENY_{aid}_{token}")
    assert "already denied" in ha_bridge.handle_action(hub, f"HLAGENTS_APPROVE_{aid}_{token}")


def test_approval_notification_carries_buttons_with_the_token(cfg, monkeypatch):
    cfg.ha_notify_services = ["mobile_app_phone_1", "mobile_app_phone_2"]
    sent = []
    monkeypatch.setattr(notify.httpx, "post", lambda url, **kw: sent.append((url, kw["json"])))
    notify.notify_approval(cfg, 7, "restart_container", {"container": "web"}, "crash loop", "TOK")
    assert [u.rsplit("/", 1)[1] for u, _ in sent] == ["mobile_app_phone_1", "mobile_app_phone_2"]
    acts = sent[0][1]["data"]["actions"]
    assert acts[0]["action"] == "HLAGENTS_APPROVE_7_TOK" and acts[1]["action"] == "HLAGENTS_DENY_7_TOK"


def test_notification_without_home_assistant_does_not_fail(cfg):
    cfg.ha_notify_services = []
    notify.notify_approval(cfg, 1, "restart_container", {}, "r", "T")      # logs only, must not raise


# ---- MCP server ------------------------------------------------------------------------------

def test_mcp_exposes_no_way_to_approve():
    names = {t.name for t in asyncio.run(mcp_server.build("s").list_tools())}
    assert names == {"ask_team", "team_status", "list_pending_approvals"}


def test_mcp_ask_team_returns_the_answer_and_pending_approvals(monkeypatch):
    calls = []

    def fake_api(method, path, **kw):
        calls.append((method, path))
        if method == "POST":
            return {"id": 5}
        return {"id": 5, "status": "needs_human", "result": "Hot water change requested.", "pending_approvals": [{"id": 2}]}
    monkeypatch.setattr(mcp_server, "_api", fake_api)
    out = asyncio.run(mcp_server.build("s").call_tool("ask_team", {"request": "set hot water to 52"}))
    text = str(out)
    assert "Hot water change requested." in text and "#2" in text
    assert calls[0] == ("POST", "/requests")


def test_mcp_ask_team_gives_up_waiting_politely(monkeypatch):
    monkeypatch.setattr(mcp_server, "WAIT_S", 0)
    monkeypatch.setattr(mcp_server, "_api", lambda m, p, **kw: {"id": 9} if m == "POST" else {"id": 9, "status": "working", "result": ""})
    assert "Still working on request 9" in str(asyncio.run(mcp_server.build("s").call_tool("ask_team", {"request": "x"})))
