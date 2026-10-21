"""MCP server so an assistant (for example Home Assistant's voice assistant) can ask the team things.

Deliberately small. It can submit a request, read a status and list what is waiting for approval.
It cannot approve or deny anything: a change is decided by a person, on the phone or the CLI.
It talks to the hlagents API, so it needs API_TOKEN and the API address.
"""
from __future__ import annotations

import os
import time

import httpx
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

API = os.environ.get("HLAGENTS_API", "http://127.0.0.1:8111")
TOKEN = os.environ.get("API_TOKEN", "")
WAIT_S = 25          # a voice assistant will not wait longer than this for an answer


def _api(method: str, path: str, **kw):
    r = httpx.request(method, API + path, headers={"Authorization": f"Bearer {TOKEN}"}, timeout=30, **kw)
    r.raise_for_status()
    return r.json()


def build(secret: str, host: str = "127.0.0.1", port: int = 8112) -> FastMCP:
    mcp = FastMCP("home-lab-team", host=host, port=port, streamable_http_path="/mcp-" + secret,
                  transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False))

    @mcp.tool()
    def ask_team(request: str) -> str:
        """Ask the home lab team (ops, home and energy, research agents) a question or give it a task, for example
        'is the searxng container healthy' or 'should we switch the heating to winter'. It looks things up and
        answers; it never changes anything by itself. Changes wait for a person to approve them."""
        tid = _api("POST", "/requests", json={"goal": request})["id"]
        end = time.monotonic() + WAIT_S
        while time.monotonic() < end:
            t = _api("GET", f"/requests/{tid}")
            if t["status"] in ("done", "failed", "needs_human"):
                return _say(t)
            time.sleep(1.5)
        return f"Still working on request {tid}. Ask for its status in a minute."

    @mcp.tool()
    def team_status(request_id: int = 0) -> str:
        """Status and answer of one request by number, or the latest requests when no number is given."""
        if request_id:
            return _say(_api("GET", f"/requests/{request_id}"))
        rows = _api("GET", "/requests")[:5]
        return "\n".join(f"#{r['id']} {r['status']}: {r['goal'][:80]}" for r in rows) or "No requests yet."

    @mcp.tool()
    def list_pending_approvals() -> str:
        """Changes the team has asked a person to approve. Approving is done on the phone or the command line, not here."""
        rows = _api("GET", "/approvals")
        return "\n".join(f"#{a['id']}: {a['action']} {a['args']} because {a['reason'][:100]}" for a in rows) or "Nothing is waiting for approval."

    return mcp


def _say(t: dict) -> str:
    text = t["result"] or f"Request {t['id']} is {t['status']}."
    if t.get("pending_approvals"):
        text += " Waiting for a person to approve: " + ", ".join(f"#{a['id']}" for a in t["pending_approvals"]) + "."
    return text


def main(cfg) -> None:
    if not (cfg.mcp_secret and TOKEN):
        raise SystemExit("set MCP_SECRET and API_TOKEN first")
    build(cfg.mcp_secret, cfg.mcp_host, cfg.mcp_port).run(transport="streamable-http")
