"""Remote API: submit a request, follow it, and decide approvals.

Protected by a bearer token and meant for the local network (a UI or an MCP server calls it).
Do not publish this port to the internet.

  POST /requests              {"goal": "...", "priority": 1}  -> {"id": N}
  GET  /requests                                              -> recent requests
  GET  /requests/N                                            -> status, result, steps
  GET  /requests/N/audit                                      -> the audit trail
  GET  /approvals                                             -> what is waiting for a decision
  POST /approvals/N/approve | /approvals/N/deny
"""
from __future__ import annotations

import hmac
import json
import logging
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import approvals
from .gate import BACKGROUND, INTERACTIVE
from .store import public_approval

log = logging.getLogger("hlagents.api")
MAX_GOAL = 1000


def _task_view(store, t: dict) -> dict:
    steps = [{"id": c["id"], "role": c["role"], "depth": c["depth"], "status": c["status"], "goal": c["goal"][:200]}
             for c in store.tree(t["root_id"]) if c["id"] != t["id"]]
    pending = [public_approval(a) for a in store.pending_approvals() if store.get_task(a["task_id"])["root_id"] == t["id"]]
    return {"id": t["id"], "status": t["status"], "goal": t["goal"], "result": t["result"], "steps": steps, "pending_approvals": pending}


def make_handler(hub):
    store, cfg = hub.store, hub.cfg

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, code: int, body) -> None:
            data = json.dumps(body, default=str).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _authed(self) -> bool:
            given = self.headers.get("Authorization", "").removeprefix("Bearer ").strip()
            ok = bool(cfg.api_token) and hmac.compare_digest(given, cfg.api_token)
            if not ok:
                self._send(401, {"error": "bad token"})
            return ok

        def _body(self) -> dict:
            n = min(int(self.headers.get("Content-Length", 0)), 16_000)
            try:
                return json.loads(self.rfile.read(n) or b"{}")
            except ValueError:
                return {}

        def do_GET(self):  # noqa: N802
            if not self._authed():
                return
            p = self.path.split("?")[0].rstrip("/")
            if p == "/requests":
                return self._send(200, [{"id": t["id"], "status": t["status"], "goal": t["goal"][:200]} for t in store.recent_roots(20)])
            if p == "/approvals":
                return self._send(200, [public_approval(a) for a in store.pending_approvals()])
            m = re.fullmatch(r"/requests/(\d+)(/audit)?", p)
            if m:
                try:
                    t = store.get_task(int(m.group(1)))
                except KeyError:
                    return self._send(404, {"error": "no such request"})
                if t["parent_id"] is not None:
                    return self._send(404, {"error": "no such request"})
                if m.group(2):
                    return self._send(200, [{"ts": r["ts"], "task": r["task_id"], "actor": r["actor"], "kind": r["kind"], "detail": r["detail"][:300]}
                                            for r in store.audit_for_root(t["root_id"])])
                return self._send(200, _task_view(store, t))
            self._send(404, {"error": "not found"})

        def do_POST(self):  # noqa: N802
            if not self._authed():
                return
            p = self.path.split("?")[0].rstrip("/")
            if p == "/requests":
                body = self._body()
                goal = str(body.get("goal", "")).strip()
                if not goal:
                    return self._send(400, {"error": "goal is required"})
                prio = BACKGROUND if body.get("priority") == 2 else INTERACTIVE
                tid = hub.submit(goal[:MAX_GOAL], priority=prio, requester="api")
                return self._send(200, {"id": tid})
            m = re.fullmatch(r"/approvals/(\d+)/(approve|deny)", p)
            if m:
                aid, verb = int(m.group(1)), m.group(2)
                try:
                    out = (approvals.approve if verb == "approve" else approvals.deny)(store, cfg, aid, "api")
                except approvals.ApprovalError as e:
                    return self._send(409, {"error": str(e)})
                return self._send(200, {"result": out})
            self._send(404, {"error": "not found"})

    return Handler


def serve_api(hub) -> ThreadingHTTPServer:
    srv = ThreadingHTTPServer((hub.cfg.api_host, hub.cfg.api_port), make_handler(hub))
    threading.Thread(target=srv.serve_forever, name="api", daemon=True).start()
    log.info("API on %s:%s", hub.cfg.api_host, hub.cfg.api_port)
    return srv
