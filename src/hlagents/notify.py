"""Tell a human something. Never raises: a failed notification must not fail a task."""
from __future__ import annotations

import logging

import httpx

from .config import Config

log = logging.getLogger("hlagents.notify")


def notify(cfg: Config, title: str, message: str) -> None:
    log.info("NOTIFY %s: %s", title, message)
    if not (cfg.ntfy_url and cfg.ntfy_topic):
        return
    try:
        httpx.post(f"{cfg.ntfy_url.rstrip('/')}/{cfg.ntfy_topic}", content=message.encode(), headers={"Title": title}, timeout=10)
    except Exception as e:  # noqa: BLE001
        log.warning("notify failed: %s", type(e).__name__)
