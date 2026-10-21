import json
import threading

import pytest

from hlagents import tools as T
from hlagents.config import Config
from hlagents.runner import Hub
from hlagents.store import Store


def say(text: str) -> dict:
    return {"role": "assistant", "content": text, "tool_calls": []}


def call(_tool: str, **args) -> dict:
    return {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": _tool, "arguments": args}}]}


class ScriptedLLM:
    """Plays back scripted replies. A script is a list of messages or callables; the key is picked from the prompt."""

    def __init__(self, **scripts):
        self.scripts = {k: list(v) for k, v in scripts.items()}
        self.lock = threading.Lock()
        self.seen: list[tuple[str, list]] = []

    @staticmethod
    def key(messages, json_schema):
        if json_schema:
            return "plan"
        s = messages[0]["content"]
        for k, marker in (("ops", "You are the ops agent"), ("home", "You are the home and energy agent"),
                          ("research", "You are the research agent"), ("summary", "Write the final answer")):
            if s.startswith(marker):
                return k
        raise AssertionError("unknown prompt: " + s[:60])

    def chat(self, messages, tools=None, priority=2, json_schema=None):
        k = self.key(messages, json_schema)
        with self.lock:
            self.seen.append((k, messages))
            queue = self.scripts.get(k)
            if not queue:
                raise AssertionError(f"no scripted reply left for '{k}'")
            item = queue.pop(0) if len(queue) > 1 or not callable(queue[0]) else queue[0]
        return item(messages) if callable(item) else item


@pytest.fixture
def cfg():
    return Config(db_path=":memory:", containers=["web", "db"], github_repos=["acme/web"], ha_url="http://ha.test",
                  ha_token="t", weather_entity="weather.home", dry_run=True, turn_limit=10, time_budget_s=20, max_calls_per_tool=6)


@pytest.fixture
def fake_docker(monkeypatch):
    calls = []

    def docker(*args):
        calls.append(args)
        if args[0] == "logs":
            return "2026-01-01 starting\n2026-01-01 listening on :8080\n"
        if args[0] == "inspect":
            return "running|3|0|2026-01-01T00:00:00Z|healthy"
        if args[0] == "ps":
            return "web|Up 2 hours|acme/web:1.2\ndb|Up 2 hours|postgres:17\nother|Up 1 hour|x:1\n"
        return ""
    monkeypatch.setattr(T, "docker", docker)
    return calls


@pytest.fixture
def fake_http(monkeypatch):
    routes = {}

    def http(method, url, **kw):
        for frag, val in routes.items():
            if frag in url:
                return val(kw) if callable(val) else val
        raise AssertionError("unexpected http call " + url)
    monkeypatch.setattr(T, "http", http)
    return routes


def make_hub(cfg, **scripts):
    hub = Hub(cfg, store=Store(":memory:"), llm=ScriptedLLM(**scripts))
    return hub


@pytest.fixture
def run_task():
    """Run one task for a role synchronously, without worker threads."""
    from hlagents.agents import run_agent

    def go(hub, role, goal, context=""):
        tid = hub.store.create_task(role, goal, requester="test", context=context)
        task = hub.store.claim_next(role)
        status, result = run_agent(hub, task)
        hub.store.finish(tid, status, result)
        return tid, status, result
    return go
