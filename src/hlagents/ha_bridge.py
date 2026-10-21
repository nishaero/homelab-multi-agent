"""Phone approval buttons through Home Assistant.

When an agent asks for approval, the phone gets a notification with Approve and Deny buttons
(see notify.notify_approval). Pressing one fires a `mobile_app_notification_action` event in Home
Assistant. This listener receives it over the websocket and decides the approval.

The button carries a one time token that exists only in that notification, so a forged event
without it is ignored.
"""
from __future__ import annotations

import asyncio
import hmac
import json
import logging
import re
import threading

import websockets

from . import approvals
from .notify import notify_result

log = logging.getLogger("hlagents.bridge")
_ACTION = re.compile(r"HLAGENTS_(APPROVE|DENY)_(\d+)_([A-Za-z0-9_\-]+)")


def handle_action(hub, action: str) -> str | None:
    """Process one button press. Returns a message for the phone, or None if it is not ours."""
    m = _ACTION.fullmatch(action or "")
    if not m:
        return None
    verb, aid, token = m.group(1), int(m.group(2)), m.group(3)
    store, cfg = hub.store, hub.cfg
    try:
        a = store.get_approval(aid)
    except KeyError:
        return None
    if not a.get("token") or not hmac.compare_digest(a["token"], token):
        store.audit(a["task_id"], "phone", "approval_bad_token", {"id": aid})
        return None
    try:
        out = approvals.approve(store, cfg, aid, "phone") if verb == "APPROVE" else approvals.deny(store, cfg, aid, "phone")
    except approvals.ApprovalError as e:
        return str(e)
    return f"Approved #{aid}: {out}" if verb == "APPROVE" else out


async def _listen(hub) -> None:
    cfg = hub.cfg
    async with websockets.connect(cfg.ha_url.replace("http", "ws", 1) + "/api/websocket", max_size=None, ping_interval=20) as ws:
        await ws.recv()
        await ws.send(json.dumps({"type": "auth", "access_token": cfg.ha_token}))
        if json.loads(await ws.recv()).get("type") != "auth_ok":
            raise RuntimeError("Home Assistant refused the token")
        await ws.send(json.dumps({"id": 1, "type": "subscribe_events", "event_type": "mobile_app_notification_action"}))
        log.info("listening for approval buttons")
        async for raw in ws:
            msg = json.loads(raw)
            if msg.get("type") != "event":
                continue
            action = (msg["event"].get("data") or {}).get("action", "")
            text = await asyncio.to_thread(handle_action, hub, action)
            if text:
                m = _ACTION.fullmatch(action)
                await asyncio.to_thread(notify_result, cfg, int(m.group(2)), text)


def start_bridge(hub) -> threading.Thread | None:
    if not (hub.cfg.ha_url and hub.cfg.ha_token and hub.cfg.ha_notify_services):
        return None

    def loop() -> None:
        while True:
            try:
                asyncio.run(_listen(hub))
            except Exception as e:  # noqa: BLE001
                log.warning("bridge error: %s", type(e).__name__)
            import time
            time.sleep(10)

    t = threading.Thread(target=loop, name="ha-bridge", daemon=True)
    t.start()
    return t
