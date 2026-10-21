"""The hub: one worker thread per role, all sharing one model gate."""
from __future__ import annotations

import logging
import threading
import time

import httpx

from . import coordinator
from .agents import ROLES, run_agent
from .config import Config
from .gate import INTERACTIVE, ModelGate
from .llm import LLM, OllamaLLM
from .store import FAILED, Store

log = logging.getLogger("hlagents")


class Hub:
    def __init__(self, cfg: Config, store: Store | None = None, llm: LLM | None = None, gate: ModelGate | None = None) -> None:
        self.cfg = cfg
        self.store = store or Store(cfg.db_path)
        self.gate = gate or ModelGate()
        self.llm = llm or OllamaLLM(cfg, self.gate)
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []

    def submit(self, goal: str, priority: int = INTERACTIVE, requester: str = "human") -> int:
        return self.store.create_task("coordinator", goal, requester=requester, priority=priority, max_depth=self.cfg.max_depth)

    def start(self) -> None:
        stale = self.store.fail_stale()
        if stale:
            log.warning("marked %d stale tasks as failed", stale)
        for role in ["coordinator", *ROLES]:
            t = threading.Thread(target=self._worker, args=(role,), name=f"worker-{role}", daemon=True)
            t.start()
            self._threads.append(t)

    def stop(self) -> None:
        self._stop.set()
        for t in self._threads:
            t.join(timeout=5)

    def _worker(self, role: str) -> None:
        while not self._stop.is_set():
            task = self.store.claim_next(role)
            if not task:
                time.sleep(0.3)
                continue
            try:
                status, result = coordinator.run_root(self, task) if role == "coordinator" else run_agent(self, task)
            except Exception as e:  # noqa: BLE001
                log.exception("task %s crashed", task["id"])
                status, result = FAILED, f"{type(e).__name__}: {e}"
            self.store.finish(task["id"], status, result)
            if role == "coordinator":
                self._remember(task, status, result)

    def _remember(self, task: dict, status: str, result: str) -> None:
        """Optional: leave a note in the shared household memory so the other agents can recall it."""
        if not self.cfg.memory_url:
            return
        try:
            httpx.post(self.cfg.memory_url.rstrip("/") + "/events", headers={"X-Token": self.cfg.memory_token}, timeout=10,
                       json={"kind": "agent_task", "text": f"Request: {task['goal'][:200]} Outcome ({status}): {result[:400]}",
                             "meta": {"task_id": task["id"]}})
        except Exception as e:  # noqa: BLE001
            log.warning("memory note failed: %s", type(e).__name__)
