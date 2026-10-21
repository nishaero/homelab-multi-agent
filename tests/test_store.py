import pytest

from hlagents.store import DepthExceeded, Store


def test_depth_limit():
    s = Store(":memory:")
    t = s.create_task("coordinator", "root", "human")
    for _ in range(3):
        t = s.create_task("ops", "child", "coordinator", parent_id=t, max_depth=3)
    with pytest.raises(DepthExceeded):
        s.create_task("ops", "too deep", "ops", parent_id=t, max_depth=3)


def test_claim_order_and_root_tracking():
    s = Store(":memory:")
    low = s.create_task("ops", "background", "human", priority=2)
    high = s.create_task("ops", "urgent", "human", priority=0)
    assert s.claim_next("ops")["id"] == high
    assert s.claim_next("ops")["id"] == low
    assert s.claim_next("ops") is None
    child = s.create_task("research", "c", "ops", parent_id=low)
    assert s.get_task(child)["root_id"] == s.get_task(low)["root_id"] == low


def test_identical_pending_approval_is_found():
    s = Store(":memory:")
    t = s.create_task("ops", "x", "human")
    s.create_approval(t, "restart_container", {"container": "web"}, "why")
    assert s.find_open_approval(t, "restart_container", {"container": "web"})
    assert not s.find_open_approval(t, "restart_container", {"container": "db"})


def test_stale_working_tasks_fail_on_restart():
    s = Store(":memory:")
    t = s.create_task("ops", "x", "human")
    s.claim_next("ops")
    assert s.fail_stale() == 1
    assert s.get_task(t)["status"] == "failed"


def test_two_processes_can_open_an_old_database_at_once(tmp_path):
    import sqlite3
    from hlagents.store import Store
    path = str(tmp_path / "old.db")
    db = sqlite3.connect(path)
    db.executescript("create table approvals(id integer primary key, task_id integer, action text, args text, reason text, status text default 'pending', decided_by text, result text, created real, decided real);")
    db.commit(); db.close()
    Store(path); Store(path)          # the second one finds the column already added
