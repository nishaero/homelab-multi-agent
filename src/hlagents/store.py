"""Task, approval and audit storage in SQLite.

Agents never talk to each other directly. They read and write rows here, so every
hand off is recorded and any process (workers, the CLI) can see the same state.
"""
from __future__ import annotations

import json
import secrets
import sqlite3
import threading
import time
from typing import Any

OPEN, WORKING, DONE, FAILED, NEEDS_HUMAN = "open", "working", "done", "failed", "needs_human"
TERMINAL = {DONE, FAILED, NEEDS_HUMAN}

SCHEMA = """
create table if not exists tasks(
  id integer primary key autoincrement, root_id integer, parent_id integer, depth integer not null default 0,
  role text not null, requester text not null, goal text not null, context text default '',
  priority integer not null default 2, status text not null default 'open',
  result text default '', created real not null, updated real not null);
create table if not exists approvals(
  id integer primary key autoincrement, task_id integer, action text not null, args text not null, reason text default '',
  status text not null default 'pending', decided_by text default '', result text default '',
  created real not null, decided real);
create table if not exists audit(
  id integer primary key autoincrement, ts real not null, task_id integer, actor text not null, kind text not null, detail text not null);
"""


def _migrate(db) -> None:
    cols = {r[1] for r in db.execute("pragma table_info(approvals)")}
    if "token" not in cols:
        try:
            db.execute("alter table approvals add column token text default ''")
        except sqlite3.OperationalError as e:      # another process added it first
            if "duplicate column" not in str(e):
                raise


class DepthExceeded(Exception):
    pass


class Store:
    def __init__(self, path: str = ":memory:") -> None:
        self._db = sqlite3.connect(path, check_same_thread=False, isolation_level=None, timeout=30)
        self._db.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        with self._lock:
            self._db.executescript(SCHEMA)
            _migrate(self._db)

    # ---- helpers
    def _one(self, sql: str, args: tuple = ()) -> dict | None:
        with self._lock:
            r = self._db.execute(sql, args).fetchone()
        return dict(r) if r else None

    def _all(self, sql: str, args: tuple = ()) -> list[dict]:
        with self._lock:
            return [dict(r) for r in self._db.execute(sql, args).fetchall()]

    # ---- tasks
    def create_task(self, role: str, goal: str, requester: str, parent_id: int | None = None, priority: int = 2,
                    context: str = "", max_depth: int = 3) -> int:
        depth, root = 0, None
        if parent_id is not None:
            parent = self.get_task(parent_id)
            depth, root = parent["depth"] + 1, parent["root_id"]
            if depth > max_depth:
                raise DepthExceeded(f"delegation depth {depth} is over the limit of {max_depth}")
        now = time.time()
        with self._lock:
            cur = self._db.execute(
                "insert into tasks(root_id,parent_id,depth,role,requester,goal,context,priority,created,updated) values(?,?,?,?,?,?,?,?,?,?)",
                (root, parent_id, depth, role, requester, goal, context, priority, now, now))
            tid = cur.lastrowid
            if root is None:
                self._db.execute("update tasks set root_id=? where id=?", (tid, tid))
        self.audit(tid, requester, "task_created", {"role": role, "goal": goal[:300], "parent": parent_id, "depth": depth})
        return tid

    def get_task(self, tid: int) -> dict:
        t = self._one("select * from tasks where id=?", (tid,))
        if not t:
            raise KeyError(f"no task {tid}")
        return t

    def claim_next(self, role: str) -> dict | None:
        with self._lock:
            row = self._db.execute(
                "select id from tasks where role=? and status='open' order by priority, id limit 1", (role,)).fetchone()
            if not row:
                return None
            self._db.execute("update tasks set status='working', updated=? where id=?", (time.time(), row["id"]))
        return self.get_task(row["id"])

    def finish(self, tid: int, status: str, result: str) -> None:
        with self._lock:
            self._db.execute("update tasks set status=?, result=?, updated=? where id=?", (status, result, time.time(), tid))
        self.audit(tid, "system", "task_" + status, {"result": result[:500]})

    def fail_stale(self) -> int:
        """Tasks left 'working' by a worker that died. Called once at start up."""
        with self._lock:
            cur = self._db.execute("update tasks set status='failed', result='worker restarted while this task was running', updated=? where status='working'", (time.time(),))
        return cur.rowcount

    def children(self, tid: int) -> list[dict]:
        return self._all("select * from tasks where parent_id=? order by id", (tid,))

    def recent_goal_exists(self, goal: str, within_s: float) -> bool:
        return self._one("select id from tasks where parent_id is null and goal=? and created>?", (goal, time.time() - within_s)) is not None

    def recent_roots(self, limit: int = 10) -> list[dict]:
        return self._all("select * from tasks where parent_id is null order by id desc limit ?", (limit,))

    def wait_for(self, tid: int, timeout: float, poll: float = 0.2) -> dict:
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            t = self.get_task(tid)
            if t["status"] in TERMINAL:
                return t
            time.sleep(poll)
        return self.get_task(tid)

    def tree(self, root_id: int) -> list[dict]:
        return self._all("select * from tasks where root_id=? order by id", (root_id,))

    # ---- approvals
    def create_approval(self, task_id: int, action: str, args: dict, reason: str) -> int:
        with self._lock:
            cur = self._db.execute("insert into approvals(task_id,action,args,reason,token,created) values(?,?,?,?,?,?)",
                                   (task_id, action, json.dumps(args, sort_keys=True), reason, secrets.token_urlsafe(9), time.time()))
        self.audit(task_id, "agent", "approval_requested", {"id": cur.lastrowid, "action": action, "args": args, "reason": reason})
        return cur.lastrowid

    def get_approval(self, aid: int) -> dict:
        a = self._one("select * from approvals where id=?", (aid,))
        if not a:
            raise KeyError(f"no approval {aid}")
        a["args"] = json.loads(a["args"])
        return a

    def pending_approvals(self) -> list[dict]:
        rows = self._all("select * from approvals where status='pending' order by id")
        for r in rows:
            r["args"] = json.loads(r["args"])
        return rows

    def decide(self, aid: int, status: str, who: str, result: str = "") -> None:
        with self._lock:
            self._db.execute("update approvals set status=?, decided_by=?, result=?, decided=? where id=?",
                             (status, who, result, time.time(), aid))
        a = self.get_approval(aid)
        self.audit(a["task_id"], who, "approval_" + status, {"id": aid, "action": a["action"], "result": result[:300]})

    def find_open_approval(self, task_id: int, action: str, args: dict) -> dict | None:
        """An identical request that is still pending, so an agent cannot spam the same one."""
        return self._one("select * from approvals where task_id=? and action=? and args=? and status='pending'",
                         (task_id, action, json.dumps(args, sort_keys=True)))

    # ---- audit
    def audit(self, task_id: int | None, actor: str, kind: str, detail: Any) -> None:
        with self._lock:
            self._db.execute("insert into audit(ts,task_id,actor,kind,detail) values(?,?,?,?,?)",
                             (time.time(), task_id, actor, kind, json.dumps(detail, default=str)))

    def audit_for_root(self, root_id: int) -> list[dict]:
        return self._all("select a.* from audit a left join tasks t on t.id=a.task_id where t.root_id=? order by a.id", (root_id,))


def public_approval(a: dict) -> dict:
    """An approval without its one time token. The token only ever goes to the phone notification."""
    return {k: v for k, v in a.items() if k != "token"}
