"""A tiny HTTP intake so existing alerting can feed the team without changing the alerting.

Point an Alertmanager webhook (or anything that can POST JSON) at it. Each distinct alert becomes one
coordinator task, at most once per hour. It only creates tasks: it cannot run a tool or an action.
"""
from __future__ import annotations

import hmac
import json
import logging
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .gate import BACKGROUND

log = logging.getLogger("hlagents.intake")
DEDUPE_S = 3600


def goals_from_payload(payload: dict) -> list[str]:
    """Alertmanager webhook format, or {"title": ..., "message": ...}."""
    out = []
    for a in payload.get("alerts") or []:
        ann, lab = a.get("annotations") or {}, a.get("labels") or {}
        if a.get("status") == "resolved":
            continue
        text = ann.get("summary") or ann.get("description") or lab.get("alertname") or "unknown alert"
        out.append(f"Alert: {text[:300]}. Find out what is wrong and what should be done.")
    if not out and (payload.get("title") or payload.get("message")):
        out.append(f"Alert: {str(payload.get('title', ''))[:100]} {str(payload.get('message', ''))[:300]}. Find out what is wrong and what should be done.")
    return out


def make_handler(hub):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):  # keep the console quiet
            pass

        def _send(self, code: int, body: dict) -> None:
            data = json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_POST(self):  # noqa: N802
            token = hub.cfg.intake_token
            given = self.headers.get("Authorization", "").removeprefix("Bearer ").strip()
            if not token or not hmac.compare_digest(given, token):
                return self._send(401, {"error": "bad token"})
            if self.path != "/alert":
                return self._send(404, {"error": "not found"})
            try:
                length = min(int(self.headers.get("Content-Length", 0)), 64_000)
                payload = json.loads(self.rfile.read(length) or b"{}")
            except ValueError:
                return self._send(400, {"error": "bad json"})
            created = []
            for goal in goals_from_payload(payload)[:5]:
                if hub.store.recent_goal_exists(goal, DEDUPE_S):
                    continue
                created.append(hub.submit(goal, priority=BACKGROUND, requester="alert"))
            self._send(200, {"created": created})

    return Handler


def serve(hub) -> ThreadingHTTPServer:
    srv = ThreadingHTTPServer((hub.cfg.serve_host, hub.cfg.serve_port), make_handler(hub))
    import threading
    threading.Thread(target=srv.serve_forever, name="intake", daemon=True).start()
    log.info("alert intake on %s:%s", hub.cfg.serve_host, hub.cfg.serve_port)
    return srv
