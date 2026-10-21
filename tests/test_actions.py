import pytest

from hlagents import actions
from hlagents.cli import cmd_approve
from hlagents.store import Store


class A:  # stand in for argparse.Namespace
    def __init__(self, id): self.id = id


def test_validation(cfg):
    assert actions.validate("set_hot_water_target", {"temperature": "50"}, cfg) == {"temperature": 50}
    for bad in ({"temperature": 99}, {"temperature": "hot"}, {}):
        with pytest.raises(actions.ActionError):
            actions.validate("set_hot_water_target", bad, cfg)
    with pytest.raises(actions.ActionError):
        actions.validate("set_heating_preset", {"preset": "Off"}, cfg)
    with pytest.raises(actions.ActionError):
        actions.validate("format_disk", {}, cfg)


def test_dry_run_does_not_execute(cfg, monkeypatch):
    monkeypatch.setattr(actions.subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not run")))
    assert actions.execute("restart_container", {"container": "web"}, cfg).startswith("dry run")


def test_live_execution_only_after_validation(cfg, monkeypatch):
    cfg.dry_run = False
    ran = []

    class P:
        returncode, stderr = 0, ""
    monkeypatch.setattr(actions.subprocess, "run", lambda cmd, **k: ran.append(cmd) or P())
    assert actions.execute("restart_container", {"container": "web"}, cfg) == "restarted web"
    assert ran == [["docker", "restart", "web"]]
    with pytest.raises(actions.ActionError):
        actions.execute("restart_container", {"container": "vault"}, cfg)
    assert len(ran) == 1


def test_approve_runs_the_action_and_records_it(cfg, capsys):
    s = Store(":memory:")
    t = s.create_task("ops", "x", "human")
    aid = s.create_approval(t, "restart_container", {"container": "web"}, "r")
    cmd_approve(A(aid), cfg, s)
    a = s.get_approval(aid)
    assert a["status"] == "executed" and a["decided_by"] == "human" and "dry run" in a["result"]
    with pytest.raises(SystemExit):
        cmd_approve(A(aid), cfg, s)      # cannot approve twice


def test_expired_request_is_refused(cfg):
    s = Store(":memory:")
    t = s.create_task("ops", "x", "human")
    aid = s.create_approval(t, "restart_container", {"container": "web"}, "r")
    cfg.approval_ttl_s = -1
    with pytest.raises(SystemExit):
        cmd_approve(A(aid), cfg, s)
    assert s.get_approval(aid)["status"] == "expired"
