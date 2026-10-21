"""Deciding an approval. One place, used by the CLI, the API and the phone buttons."""
from __future__ import annotations

import time

from . import actions
from .config import Config
from .store import Store


class ApprovalError(Exception):
    pass


def _open(store: Store, cfg: Config, aid: int) -> dict:
    try:
        a = store.get_approval(aid)
    except KeyError:
        raise ApprovalError(f"no approval #{aid}") from None
    if a["status"] != "pending":
        raise ApprovalError(f"approval #{aid} is already {a['status']}")
    if time.time() - a["created"] > cfg.approval_ttl_s:
        store.decide(aid, "expired", "system")
        raise ApprovalError(f"approval #{aid} is too old and has expired. Ask again.")
    return a


def approve(store: Store, cfg: Config, aid: int, who: str = "human") -> str:
    a = _open(store, cfg, aid)
    try:
        result = actions.execute(a["action"], a["args"], cfg)
    except Exception as e:  # noqa: BLE001
        store.decide(aid, "failed", who, f"{type(e).__name__}: {e}")
        raise ApprovalError(f"failed: {e}") from None
    store.decide(aid, "executed", who, result)
    return result


def deny(store: Store, cfg: Config, aid: int, who: str = "human") -> str:
    _open(store, cfg, aid)
    store.decide(aid, "denied", who)
    return f"denied #{aid}"
