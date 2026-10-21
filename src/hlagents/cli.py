"""Command line: submit a request, run the workers, approve or deny changes, read the audit trail."""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time

from . import approvals
from .config import Config
from .gate import BACKGROUND, INTERACTIVE
from .api import serve_api
from .ha_bridge import start_bridge
from .intake import serve
from .runner import Hub
from .store import TERMINAL, Store


def _fmt_task(t: dict) -> str:
    return f"#{t['id']} [{t['status']}] {t['role']} (depth {t['depth']}): {t['goal'][:90]}"


def cmd_submit(args, cfg, store):
    hub = Hub(cfg, store)
    tid = hub.submit(args.goal, priority=BACKGROUND if args.background else INTERACTIVE)
    print(f"submitted task #{tid}")
    if args.wait:
        t = store.wait_for(tid, timeout=args.timeout)
        print(f"\n[{t['status']}]\n{t['result'] or '(still running, run the workers with: hlagents run)'}")
        for a in store.pending_approvals():
            print(f"approval #{a['id']}: {a['action']} {json.dumps(a['args'])}  ->  hlagents approve {a['id']}")


def cmd_run(args, cfg, store):
    hub = Hub(cfg, store)
    hub.start()
    if cfg.intake_token:
        serve(hub)
    if cfg.api_token:
        serve_api(hub)
    if start_bridge(hub):
        print("phone approval buttons enabled")
    print(f"workers running (dry_run={cfg.dry_run}, model={cfg.model}). Ctrl+C to stop.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        hub.stop()


def cmd_status(args, cfg, store):
    if args.id:
        t = store.get_task(args.id)
        print(_fmt_task(t))
        for c in store.tree(t["root_id"]):
            if c["id"] != t["id"]:
                print("  " + "  " * (c["depth"] - 1) + _fmt_task(c))
        print("\n" + (t["result"] or "(no result yet)"))
    else:
        for t in store.recent_roots():
            print(_fmt_task(t))


def cmd_pending(args, cfg, store):
    rows = store.pending_approvals()
    for a in rows:
        print(f"#{a['id']} task {a['task_id']}: {a['action']} {json.dumps(a['args'])}\n   reason: {a['reason']}")
    if not rows:
        print("nothing waiting for approval")


def cmd_approve(args, cfg, store):
    try:
        print(approvals.approve(store, cfg, args.id))
    except approvals.ApprovalError as e:
        sys.exit(str(e))


def cmd_deny(args, cfg, store):
    try:
        print(approvals.deny(store, cfg, args.id))
    except approvals.ApprovalError as e:
        sys.exit(str(e))


def cmd_audit(args, cfg, store):
    root = store.get_task(args.id)["root_id"]
    for r in store.audit_for_root(root):
        print(f"{time.strftime('%H:%M:%S', time.localtime(r['ts']))} task {r['task_id']} {r['actor']:<12} {r['kind']:<20} {r['detail'][:200]}")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="hlagents")
    ap.add_argument("--config")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("submit"); s.add_argument("goal"); s.add_argument("--wait", action="store_true")
    s.add_argument("--background", action="store_true"); s.add_argument("--timeout", type=int, default=600); s.set_defaults(fn=cmd_submit)
    sub.add_parser("run").set_defaults(fn=cmd_run)
    sub.add_parser("mcp").set_defaults(fn=lambda a, c, s: __import__("hlagents.mcp_server", fromlist=["main"]).main(c))
    s = sub.add_parser("status"); s.add_argument("id", type=int, nargs="?"); s.set_defaults(fn=cmd_status)
    sub.add_parser("pending").set_defaults(fn=cmd_pending)
    for name, fn in (("approve", cmd_approve), ("deny", cmd_deny)):
        s = sub.add_parser(name); s.add_argument("id", type=int); s.set_defaults(fn=fn)
    s = sub.add_parser("audit"); s.add_argument("id", type=int); s.set_defaults(fn=cmd_audit)
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    cfg = Config.load(args.config)
    args.fn(args, cfg, None if args.cmd == "mcp" else Store(cfg.db_path))   # the MCP server only uses the API


if __name__ == "__main__":
    main()
