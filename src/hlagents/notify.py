"""Tell a human something. Never raises: a failed notification must not fail a task."""
from __future__ import annotations

import json
import logging

import httpx

from .config import Config

log = logging.getLogger("hlagents.notify")


def notify_approval(cfg: Config, aid: int, action: str, args: dict, reason: str, token: str) -> None:
    """Ask for a decision. With Home Assistant notify services configured, the phone gets Approve and Deny buttons."""
    text = f"#{aid} {action} {json.dumps(args)}\nReason: {reason[:300]}"
    if cfg.ha_url and cfg.ha_token and cfg.ha_notify_services:
        data = {"tag": f"hlagents-{aid}", "actions": [
            {"action": f"HLAGENTS_APPROVE_{aid}_{token}", "title": "Approve"},
            {"action": f"HLAGENTS_DENY_{aid}_{token}", "title": "Deny", "destructive": True}]}
        for svc in cfg.ha_notify_services:
            try:
                httpx.post(f"{cfg.ha_url}/api/services/notify/{svc}", timeout=10, headers={"Authorization": f"Bearer {cfg.ha_token}"},
                           json={"title": "Approval needed", "message": text, "data": data})
            except Exception as e:  # noqa: BLE001
                log.warning("phone notification failed: %s", type(e).__name__)
        return
    notify(cfg, "Approval needed", text + f"\nApprove with: hlagents approve {aid}")


def notify_result(cfg: Config, aid: int, text: str) -> None:
    """Tell the phones how a decision turned out, replacing the buttons."""
    if cfg.ha_url and cfg.ha_token and cfg.ha_notify_services:
        for svc in cfg.ha_notify_services:
            try:
                httpx.post(f"{cfg.ha_url}/api/services/notify/{svc}", timeout=10, headers={"Authorization": f"Bearer {cfg.ha_token}"},
                           json={"title": f"Request #{aid}", "message": text, "data": {"tag": f"hlagents-{aid}"}})
            except Exception as e:  # noqa: BLE001
                log.warning("phone notification failed: %s", type(e).__name__)
    else:
        notify(cfg, f"Request #{aid}", text)


def notify(cfg: Config, title: str, message: str) -> None:
    log.info("NOTIFY %s: %s", title, message)
    if not (cfg.ntfy_url and cfg.ntfy_topic):
        return
    try:
        httpx.post(f"{cfg.ntfy_url.rstrip('/')}/{cfg.ntfy_topic}", content=message.encode(), headers={"Title": title}, timeout=10)
    except Exception as e:  # noqa: BLE001
        log.warning("notify failed: %s", type(e).__name__)
